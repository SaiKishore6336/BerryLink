package app.berrylink.companion.discovery

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Handler
import android.os.Looper
import app.berrylink.companion.model.DiscoveredDesktop
import app.berrylink.companion.security.Fingerprint
import java.net.Inet4Address
import java.net.InetAddress
import java.util.ArrayDeque

class NsdDiscovery(
    context: Context,
    private val onChanged: (List<DiscoveredDesktop>) -> Unit,
    private val onStatus: (String, Boolean) -> Unit,
) {
    companion object {
        const val SERVICE_TYPE = "_berrylink._tcp."
    }

    private val nsdManager = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val main = Handler(Looper.getMainLooper())
    private val services = LinkedHashMap<String, DiscoveredDesktop>()
    private val queue = ArrayDeque<NsdServiceInfo>()
    private val retried = HashSet<String>()
    @Volatile private var resolving = false
    @Volatile private var running = false
    @Volatile private var starting = false
    @Volatile private var generation = 0
    private var listener: NsdManager.DiscoveryListener? = null

    /**
     * Start discovery once. Reusing the still-active listener avoids Android's
     * asynchronous stop/start race and FAILURE_ALREADY_ACTIVE on quick taps.
     */
    fun start() {
        if (running || starting) return
        generation += 1
        val gen = generation
        services.clear()
        queue.clear()
        retried.clear()
        resolving = false
        onChanged(emptyList())
        onStatus("Looking for BerryLink desktops…", true)
        starting = true
        val nextListener = listenerFor(gen)
        listener = nextListener
        try {
            nsdManager.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, nextListener)
        } catch (_: Exception) {
            if (gen == generation) {
                starting = false
                running = false
                listener = null
                onStatus("Wi-Fi discovery could not start. Enter the desktop address manually.", true)
            }
        }
    }

    /**
     * Keep the existing service discovery alive. Android already reports new
     * services as they appear, so a stop/start cycle is unnecessary and racy.
     */
    fun refresh() {
        if (running || starting) {
            publish(
                if (services.isEmpty()) "Looking for BerryLink desktops…"
                else "Found ${services.size} desktop(s).",
                false,
            )
            return
        }
        start()
    }

    fun stop() {
        generation += 1
        running = false
        starting = false
        queue.clear()
        resolving = false
        val oldListener = listener
        listener = null
        if (oldListener != null) {
            try {
                nsdManager.stopServiceDiscovery(oldListener)
            } catch (_: Exception) {
            }
        }
    }

    fun clear() {
        services.clear()
        onChanged(emptyList())
    }

    private fun listenerFor(gen: Int) = object : NsdManager.DiscoveryListener {
        override fun onDiscoveryStarted(serviceType: String) {
            if (gen != generation) return
            starting = false
            running = true
            publish("Looking for BerryLink desktops…", false)
        }

        override fun onServiceFound(serviceInfo: NsdServiceInfo) {
            if (gen != generation || !running) return
            enqueue(serviceInfo, gen)
        }

        override fun onServiceLost(serviceInfo: NsdServiceInfo) {
            if (gen != generation) return
            main.post {
                if (gen != generation) return@post
                if (services.remove(serviceInfo.serviceName) != null) {
                    publish(
                        if (services.isEmpty()) "No desktops found yet. Make sure the desktop is on this Wi-Fi."
                        else "Found ${services.size} desktop(s).",
                        false,
                    )
                }
            }
        }

        override fun onDiscoveryStopped(serviceType: String) {
            if (gen != generation) return
            running = false
            starting = false
        }

        override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
            if (gen != generation) return
            starting = false
            running = false
            listener = null
            publish(discoveryError(errorCode), true)
        }

        override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
            if (gen != generation) return
            running = false
            starting = false
        }
    }

    private fun enqueue(info: NsdServiceInfo, gen: Int) {
        if (gen != generation) return
        queue.addLast(info)
        pump(gen)
    }

    private fun pump(gen: Int) {
        if (resolving || queue.isEmpty() || gen != generation) return
        val info = queue.removeFirst()
        resolving = true
        try {
            @Suppress("DEPRECATION")
            nsdManager.resolveService(info, object : NsdManager.ResolveListener {
                override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                    if (gen != generation) return
                    resolving = false
                    val name = serviceInfo.serviceName
                    if (retried.add(name)) {
                        main.postDelayed({
                            if (gen == generation) {
                                queue.addLast(serviceInfo)
                                pump(gen)
                            }
                        }, 700)
                    }
                    pump(gen)
                }

                override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                    if (gen != generation) return
                    resolving = false
                    handleResolved(serviceInfo)
                    pump(gen)
                }
            })
        } catch (_: Exception) {
            resolving = false
            main.postDelayed({ pump(gen) }, 300)
        }
    }

    private fun handleResolved(info: NsdServiceInfo) {
        val host = preferredHost(info.host) ?: return
        val port = info.port
        if (port !in 1..65535) return
        val attributes = info.attributes ?: emptyMap()
        val fingerprint = Fingerprint.normalize(attributes["fp"]?.toString(Charsets.UTF_8))
            ?: return
        val displayName = attributes["name"]?.toString(Charsets.UTF_8)
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?: info.serviceName.substringBefore("._").replace('_', ' ')
        val desktop = DiscoveredDesktop(
            serviceName = info.serviceName,
            displayName = displayName,
            host = host,
            port = port,
            fingerprint = fingerprint,
        )
        services[info.serviceName] = desktop
        publish("Found ${services.size} desktop(s).", false)
    }

    private fun publish(message: String, _error: Boolean) {
        val list = services.values.sortedBy { it.displayName.lowercase() }
        main.post {
            onChanged(list)
            onStatus(message, false)
        }
    }

    private fun preferredHost(address: InetAddress?): String? {
        if (address == null) return null
        val host = address.hostAddress ?: return null
        return if (address is Inet4Address) host else host.substringBefore('%')
    }

    private fun discoveryError(code: Int): String = when (code) {
        NsdManager.FAILURE_ALREADY_ACTIVE -> "Discovery is already active."
        NsdManager.FAILURE_MAX_LIMIT -> "Too many discovery requests. Try again in a moment."
        else -> "Wi-Fi discovery failed. Enter the desktop address manually."
    }
}
