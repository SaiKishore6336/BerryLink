package app.berrylink.companion.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class WireTest {
    private val response =
        """{"protocol":1,"id":"msg-1","kind":"response","reply_to":"req-1","ok":true,""" +
            """"payload":{"reply":"  Right there.  ","provider":"gemini","model":"gemini-3.8-flash",""" +
            """"mood":"happy","tools_used":["point_at","look_at_screen"],"effects":["pointing"],""" +
            """"notice":"Mock note"}}"""

    @Test
    fun requestCarriesVersionMethodAndJsonObjectPayload() {
        val request = Wire.request("ping")
        val raw = Wire.payloadOf(request.text)
        assertEquals(1, raw["protocol"]?.jsonPrimitive?.content?.toInt())
        assertEquals("request", raw["kind"]?.jsonPrimitive?.content)
        assertEquals("ping", raw["method"]?.jsonPrimitive?.content)
        assertEquals(request.id, raw["id"]?.jsonPrimitive?.content)
        assertTrue(raw["payload"] is kotlinx.serialization.json.JsonObject)
        assertNotNull(raw["ts"])
    }

    @Test
    fun parseResponseAndMapAskReply() {
        val message = Wire.parse(response)
        assertEquals("response", message.kind)
        assertEquals("req-1", message.replyTo)
        assertTrue(message.ok == true)
        assertEquals("Mock note", message.payload?.get("notice")?.jsonPrimitive?.content)

        val reply = Wire.askReply(message)
        assertEquals("Right there.", reply.reply)
        assertEquals("gemini", reply.provider)
        assertEquals("gemini-3.8-flash", reply.model)
        assertEquals("happy", reply.mood)
        assertEquals(listOf("point_at", "look_at_screen"), reply.toolsUsed)
        assertEquals(listOf("pointing"), reply.effects)
        assertEquals("Mock note", reply.notice)
    }

    @Test
    fun parseErrorResponse() {
        val message = Wire.parse(
            """{"protocol":1,"id":"m2","kind":"response","reply_to":"r2","ok":false,""" +
                """"error":{"code":"auth_required","message":"Pair first."}}""",
        )
        assertFalse(message.ok ?: true)
        assertEquals("auth_required", message.errorCode)
        assertEquals("Pair first.", message.errorMessage)
        val remote = Wire.errorFrom(message)
        assertEquals("auth_required", remote.code)
        assertEquals("Pair first.", remote.message)
    }

    @Test
    fun pairResultRequiresDeviceAndToken() {
        val message = Wire.parse(
            """{"protocol":1,"id":"m3","kind":"response","reply_to":"r3","ok":true,"payload":{""" +
                """"device_id":"dev-1","token":"secret","desktop_name":"kali",""" +
                """"certificate_fingerprint":"AA:BB"}}""",
        )
        val result = Wire.pairResult(message)
        assertEquals("dev-1", result.deviceId)
        assertEquals("secret", result.token)
        assertEquals("kali", result.desktopName)
        assertEquals("AA:BB", result.fingerprint)

        try {
            Wire.pairResult(
                Wire.parse(
                    """{"protocol":1,"id":"m4","kind":"response","reply_to":"r4","ok":true,""" +
                        """"payload":{"device_id":"dev-1"}}""",
                ),
            )
            fail("pairResult accepted a response with no token")
        } catch (expected: IllegalArgumentException) {
            assertTrue(expected.message.orEmpty().contains("token"))
        }
    }

    @Test
    fun rejectsWrongProtocolAndMalformedEnvelopes() {
        assertRejected("""{"protocol":2,"id":"m","kind":"event","method":"x","payload":{}}""")
        assertRejected("""{"id":"m","kind":"event","method":"x","payload":{}}""")
        assertRejected("""not json""")
        assertRejected("""[]""")
        assertRejected("""{"protocol":1,"id":"m","kind":"event"}""")
    }

    @Test
    fun stringListIgnoresNonStringsAndBadArrays() {
        val message = Wire.parse(
            """{"protocol":1,"id":"m5","kind":"event","method":"status","payload":{"items":["one",2,null,"two"]}}""",
        )
        assertEquals(listOf("one", "two"), message.stringList("items"))
        assertTrue(message.stringList("missing").isEmpty())
        assertNull(message.text("missing"))
    }

    @Test
    fun textBooleanHelpersAreStrict() {
        val message = Wire.parse(
            """{"protocol":1,"id":"m6","kind":"event","method":"status","payload":{"flag":true,"text":"hi","odd":"TRUE"}}""",
        )
        assertEquals("hi", message.text("text"))
        assertEquals(true, message.boolean("flag"))
        assertNull(message.boolean("odd"))
    }

    @Test
    fun numberHelpersAcceptNumericPayloadsOnly() {
        val message = Wire.parse(
            """{"protocol":1,"id":"m7","kind":"event","method":"cursor",""" +
                """"payload":{"x":0.56,"y":-0.28,"bad":"nope","nan":null}}""",
        )
        assertEquals(0.56f, message.number("x"))
        assertEquals(-0.28f, message.number("y"))
        assertNull(message.number("bad"))
        assertNull(message.number("nan"))
        assertNull(message.number("missing"))
    }

    private fun assertRejected(text: String) {
        try {
            Wire.parse(text)
            fail("accepted malformed envelope: $text")
        } catch (_: IllegalArgumentException) {
            // expected
        }
    }
}
