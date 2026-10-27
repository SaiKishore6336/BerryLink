package app.berrylink.companion.protocol

import app.berrylink.companion.model.AskReply
import app.berrylink.companion.model.PairResult
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.util.UUID

const val PROTOCOL_VERSION = 1

class RemoteException(
    val code: String,
    override val message: String,
) : Exception(message)

data class WireMessage(
    val kind: String,
    val id: String,
    val method: String?,
    val payload: JsonObject?,
    val replyTo: String?,
    val ok: Boolean?,
    val errorCode: String?,
    val errorMessage: String?,
) {
    fun text(field: String): String? = payload?.get(field)?.let(::stringOrNull)

    fun boolean(field: String): Boolean? = (payload?.get(field) as? JsonPrimitive)?.content?.toBooleanStrictOrNull()

    fun number(field: String): Float? = (payload?.get(field) as? JsonPrimitive)
        ?.content
        ?.toFloatOrNull()
        ?.takeIf { it.isFinite() }

    fun stringList(field: String): List<String> {
        val array = payload?.get(field) as? JsonArray ?: return emptyList()
        return array.mapNotNull { stringOrNull(it) }
    }
}

data class WireRequest(val id: String, val text: String)

object Wire {
    private val json = Json { ignoreUnknownKeys = true }

    fun newId(): String = UUID.randomUUID().toString().replace("-", "")

    fun request(method: String, payload: JsonObject = JsonObject(emptyMap())): WireRequest {
        val id = newId()
        val envelope = buildJsonObject {
            put("protocol", PROTOCOL_VERSION)
            put("id", id)
            put("kind", "request")
            put("method", method)
            put("payload", payload)
            put("ts", System.currentTimeMillis())
        }
        return WireRequest(id, envelope.toString())
    }

    fun payloadOf(jsonText: String): JsonObject {
        val element = runCatching { json.parseToJsonElement(jsonText) }.getOrNull()
            ?: throw IllegalArgumentException("Malformed desktop message.")
        return element as? JsonObject
            ?: throw IllegalArgumentException("Malformed desktop message.")
    }

    fun parse(jsonText: String): WireMessage {
        val raw = payloadOf(jsonText)
        val protocol = (raw["protocol"] as? JsonPrimitive)?.content?.toIntOrNull()
        if (protocol != PROTOCOL_VERSION) {
            throw IllegalArgumentException("This desktop uses a different BerryLink protocol.")
        }
        val kind = stringOrNull(raw["kind"]) ?: throw IllegalArgumentException("Missing message kind.")
        if (kind !in setOf("request", "response", "event")) {
            throw IllegalArgumentException("Unknown message kind.")
        }
        val id = stringOrNull(raw["id"]) ?: throw IllegalArgumentException("Missing message id.")
        if (id.isBlank()) throw IllegalArgumentException("Missing message id.")
        val payloadElement = raw["payload"]
        if (payloadElement != null && payloadElement !is JsonObject) {
            throw IllegalArgumentException("Message payload must be an object.")
        }
        val payload = payloadElement as? JsonObject
        val method = stringOrNull(raw["method"])
        val replyTo = stringOrNull(raw["reply_to"])
        val ok = (raw["ok"] as? JsonPrimitive)?.content?.toBooleanStrictOrNull()
        if (kind == "request" || kind == "event") {
            if (method.isNullOrBlank()) throw IllegalArgumentException("Missing message method.")
        } else {
            if (replyTo.isNullOrBlank()) throw IllegalArgumentException("Missing reply_to.")
            if (ok == null) throw IllegalArgumentException("Missing response status.")
        }
        val error = raw["error"] as? JsonObject
        return WireMessage(
            kind = kind,
            id = id,
            method = method,
            payload = payload,
            replyTo = replyTo,
            ok = ok,
            errorCode = stringOrNull(error?.get("code")),
            errorMessage = stringOrNull(error?.get("message")),
        )
    }

    fun pairResult(message: WireMessage): PairResult {
        val payload = message.payload ?: throw IllegalArgumentException("Desktop sent no pairing details.")
        val deviceId = stringOrNull(payload["device_id"]) ?: throw IllegalArgumentException("Desktop did not return a device id.")
        val token = stringOrNull(payload["token"]) ?: throw IllegalArgumentException("Desktop did not return a device token.")
        val desktopName = stringOrNull(payload["desktop_name"]) ?: "BerryLink desktop"
        val fingerprint = stringOrNull(payload["certificate_fingerprint"]).orEmpty()
        return PairResult(deviceId, token, desktopName, fingerprint)
    }

    fun askReply(message: WireMessage): AskReply {
        val payload = message.payload ?: throw IllegalArgumentException("The desktop sent an empty answer.")
        val reply = stringOrNull(payload["reply"])?.trim().orEmpty()
        if (reply.isEmpty()) throw IllegalArgumentException("The desktop sent an empty answer.")
        val tools = message.stringList("tools_used")
        val effects = message.stringList("effects")
        return AskReply(
            reply = reply,
            provider = stringOrNull(payload["provider"]) ?: "unknown",
            model = stringOrNull(payload["model"]) ?: "unknown",
            mood = stringOrNull(payload["mood"]) ?: "happy",
            toolsUsed = tools,
            effects = effects,
            notice = stringOrNull(payload["notice"]),
        )
    }

    fun errorFrom(message: WireMessage): RemoteException =
        RemoteException(
            message.errorCode ?: "desktop_error",
            message.errorMessage ?: "The desktop could not complete that request.",
        )
}

internal fun stringOrNull(element: JsonElement?): String? {
    val primitive = element as? JsonPrimitive ?: return null
    return if (primitive.isString) primitive.content else null
}

fun jsonObjectOf(vararg pairs: Pair<String, JsonElement>): JsonObject = JsonObject(mapOf(*pairs))

fun jsonString(value: String): JsonElement = JsonPrimitive(value)

fun jsonInt(value: Int): JsonElement = JsonPrimitive(value)

fun jsonBool(value: Boolean): JsonElement = JsonPrimitive(value)

fun JsonObject.arraySize(field: String): Int = (this[field] as? JsonArray)?.size ?: 0

fun JsonObject.stringAt(field: String): String? = stringOrNull(this[field])

fun JsonObject.objectAt(field: String): JsonObject? = this[field] as? JsonObject

fun JsonObject.arrayAt(field: String): JsonArray? = this[field] as? JsonArray

fun JsonElement.asStringList(): List<String> = (this as? JsonArray)?.mapNotNull(::stringOrNull) ?: emptyList()

fun JsonObject.obj(field: String): JsonObject = this[field]?.jsonObject ?: JsonObject(emptyMap())

fun JsonObject.arr(field: String): JsonArray = this[field]?.jsonArray ?: JsonArray(emptyList())

fun JsonObject.textValue(field: String): String? = this[field]?.jsonPrimitive?.content
