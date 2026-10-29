package ai.vaquill.sdk

import ai.vaquill.sdk.resources.DivisionFilters
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.time.Instant
import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

private fun sample(name: String, vararg extra: Pair<String, JsonElement>): JsonObject =
    JsonObject(Spec.sample(Spec.schemas[name]!!.jsonObject).jsonObject + extra)

private fun page(items: List<JsonElement>, key: String, vararg extra: Pair<String, JsonElement>): String =
    JsonObject(mapOf(key to JsonArray(items)) + extra).toString()

private fun n(v: Long) = JsonPrimitive(v)
private fun b(v: Boolean) = JsonPrimitive(v)

class PaginationTest {
    private val hit = sample("StatuteResult")

    @Test
    fun searchFollowsNextOffsetOrHasMoreAndGuardsApply() = runBlocking<Unit> {
        FakeServer().use { s ->
            s.script(
                Reply(200, page(listOf(hit, hit), "results", "hasMore" to b(true), "nextOffset" to JsonNull)),
                Reply(200, page(listOf(hit), "results", "hasMore" to b(true), "nextOffset" to n(7))),
                Reply(200, page(listOf(hit), "results", "hasMore" to b(false))),
            )
            val p = client(s).statutes.iterSearch("q")
            assertEquals(4, p.toList().size)
            assertEquals(listOf(0, 2, 7), s.requests.map { it.json().jsonObject["offset"]!!.jsonPrimitive.content.toInt() })
            assertTrue(s.requests.all { it.header("idempotency-key") != null })
            assertFalse(p.truncated)
            assertFalse(p.stuck)
        }
        FakeServer().use { s ->
            s.script(Reply(200, page(listOf(hit, hit), "results", "hasMore" to b(true))))
            val maxItems = client(s).statutes.iterSearch("q", maxItems = 3)
            assertEquals(3, maxItems.toList().size)
            assertTrue(maxItems.truncated)
            val maxPages = client(s).statutes.iterSearch("q", maxPages = 1)
            assertEquals(1, maxPages.pages().toList().size)
            assertTrue(maxPages.truncated)
        }
    }

    @Test
    fun serverRepeatingItsPositionOrAnEmptyHasMorePageStopsTheLoop() = runBlocking<Unit> {
        FakeServer().use { s ->
            s.script(Reply(200, page(listOf(hit), "results", "hasMore" to b(true), "nextOffset" to n(0))))
            val p = client(s).statutes.iterSearch("q")
            assertEquals(1, p.toList().size)
            assertTrue(p.stuck)
            assertEquals(1, s.requests.size)
        }
        FakeServer().use { s ->
            s.script(Reply(200, page(emptyList(), "results", "hasMore" to b(true))))
            val p = client(s).statutes.iterSearch("q")
            assertEquals(0, p.toList().size)
            assertTrue(p.stuck)
        }
    }

    @Test
    fun divisionsFollowCursors() = runBlocking<Unit> {
        FakeServer().use { s ->
            val node = sample("UsDivisionNode")
            s.responder = { r, _ ->
                if (r.rawQuery!!.contains("cursor=c2")) Reply(200, page(listOf(node), "divisions", "nextCursor" to JsonNull))
                else Reply(200, page(listOf(node), "divisions", "nextCursor" to JsonPrimitive("c2")))
            }
            val out = client(s).statutes.iterDivisions("usc", DivisionFilters(titleNumber = 42, excludeRepealed = true)).toList()
            assertEquals(2, out.size)
            assertEquals("corpusType=usc&titleNumber=42&excludeRepealed=true", s.requests[0].rawQuery)
            assertEquals("corpusType=usc&titleNumber=42&excludeRepealed=true&cursor=c2", s.requests[1].rawQuery)
        }
    }

    @Test
    fun idWindowsWalkBackwardAndForward() = runBlocking<Unit> {
        FakeServer().use { s ->
            fun ev(id: Long) = sample("StatuteChangeEvent", "id" to n(id))
            s.script(
                Reply(200, page(listOf(ev(5), ev(4)), "changes", "hasMore" to b(true))),
                Reply(200, page(listOf(ev(3)), "changes")),
            )
            val items = client(s).statutes.iterSectionChanges("a b", limit = 2, changeKind = listOf("added", "amended")).toList()
            assertEquals(3, items.size)
            assertEquals("/api/v1/us/statutes/section/a%20b/changes", s.requests[0].rawPath)
            assertEquals("limit=2&changeKind=added&changeKind=amended&order=desc", s.requests[0].rawQuery)
            assertEquals("limit=2&changeKind=added&changeKind=amended&order=desc&beforeId=4", s.requests[1].rawQuery)
        }
        FakeServer().use { s ->
            fun ch(id: Long) = sample("SessionLawChange", "id" to n(id))
            s.script(Reply(200, page(listOf(ch(1), ch(2)), "changes", "hasMore" to b(true))), Reply(200, page(listOf(ch(3)), "changes", "hasMore" to b(false))))
            assertEquals(3, client(s).sessionLaws.iterChanges(limit = 2, jurisdiction = "tx").toList().size)
            assertTrue(s.requests[1].rawQuery!!.contains("sinceId=2"))
        }
    }

    @Test
    fun freeEndpointsUnwrapTheDataEnvelope() = runBlocking<Unit> {
        FakeServer().use { s ->
            val w = sample("WatchResponse")
            s.script(
                Reply(200, JsonObject(mapOf("data" to JsonObject(mapOf("watches" to JsonArray(listOf(w, w)), "hasMore" to b(true))))).toString()),
                Reply(200, JsonObject(mapOf("data" to JsonObject(mapOf("watches" to JsonArray(listOf(w)), "hasMore" to b(false))))).toString()),
            )
            assertEquals(3, client(s).watches.iterList(limit = 2).toList().size)
            assertEquals("limit=2&offset=2", s.requests[1].rawQuery)
            assertTrue(s.requests.all { it.header("idempotency-key") == null })
        }
        FakeServer().use { s ->
            val bd = sample("BoardResponse")
            s.script(Reply(200, JsonObject(mapOf("data" to JsonObject(mapOf("boards" to JsonArray(listOf(bd)), "hasMore" to b(false))))).toString()))
            assertEquals(1, client(s).boards.iterList(corpusType = "usc", state = "tx").toList().size)
            assertEquals("corpusType=usc&state=tx&limit=500&offset=0", s.requests[0].rawQuery)
        }
        FakeServer().use { s ->
            val ch = sample("ChangeResponse", "id" to n(9))
            s.script(Reply(200, JsonObject(mapOf("data" to JsonObject(mapOf("changes" to JsonArray(listOf(ch)), "hasMore" to b(false))))).toString()))
            assertEquals(1, client(s).watches.iterChanges("w", order = "asc", since = "2026-01-01T00:00:00Z").toList().size)
            assertEquals("limit=50&since=2026-01-01T00%3A00%3A00Z&order=asc", s.requests[0].rawQuery)
        }
    }

    @Test
    fun sessionLawListSearchAndBodyPaging() = runBlocking<Unit> {
        FakeServer().use { s ->
            val sum = sample("SessionLawSummary")
            s.script(Reply(200, page(listOf(sum), "results", "nextCursor" to JsonPrimitive("n1"))), Reply(200, page(listOf(sum), "results")))
            assertEquals(2, client(s).sessionLaws.iterList("tx").toList().size)
            assertEquals("jurisdiction=tx&cursor=n1", s.requests[1].rawQuery)
        }
        FakeServer().use { s ->
            val r = sample("SessionLawSearchResult")
            s.script(Reply(200, page(listOf(r, r), "results", "hasMore" to b(true))), Reply(200, page(listOf(r), "results", "hasMore" to b(false))))
            assertEquals(3, client(s).sessionLaws.iterSearch("q", limit = 2).toList().size)
            assertEquals(2, s.requests[1].json().jsonObject["offset"]!!.jsonPrimitive.content.toInt())
        }
        FakeServer().use { s ->
            s.script(
                Reply(200, sample("SessionLawBodyResponse", "nextCursor" to JsonPrimitive("n1"), "hasMore" to b(true), "pageEnd" to n(10), "totalChars" to n(20)).toString()),
                Reply(200, sample("SessionLawBodyResponse", "nextCursor" to JsonPrimitive("n2"), "hasMore" to b(true), "pageEnd" to n(20), "totalChars" to n(20)).toString()),
            )
            val pages = client(s).sessionLaws.iterBody("sl/1", startChar = 5, version = 2).toList()
            assertEquals(2, pages.size)
            assertEquals("startChar=5&version=2", s.requests[0].rawQuery)
            assertEquals("version=2&cursor=n1", s.requests[1].rawQuery, "startChar is dropped once a cursor addresses the page")
            assertEquals("/api/v1/us/session-laws/sl%2F1/body", s.requests[0].rawPath)
        }
    }

    @Test
    fun batchHelpersChunkDedupeAndSuffixCallerKeys() = runBlocking<Unit> {
        val ids = (1..501).map { "c$it" } + listOf("c1", "c2")
        FakeServer().use { s ->
            s.script(Reply(200, Spec.sample(Spec.schemas["StatuteResolveBatchResponse"]!!.jsonObject).toString()))
            val res = client(s).statutes.resolveBatchAll(ids, state = "tx", options = RequestOptions(idempotencyKey = "k".repeat(255)))
            assertTrue(res.isEmpty())
            val sizes = s.requests.map { it.json().jsonObject["citations"]!!.jsonArray.size }
            assertEquals(listOf(500, 1), sizes)
            assertEquals("k".repeat(255), s.requests[0].header("idempotency-key"))
            assertEquals("k".repeat(253) + "-1", s.requests[1].header("idempotency-key"))
        }
        FakeServer().use { s ->
            s.script(Reply(200, Spec.sample(Spec.schemas["StatuteSectionsResponse"]!!.jsonObject).toString()))
            client(s).statutes.getSectionsAll((1..51).map { "a$it" }, includeBody = true)
            assertEquals(listOf(50, 1), s.requests.map { it.json().jsonObject["actIds"]!!.jsonArray.size })
            assertNotEqualKeys(s)
        }
        FakeServer().use { s ->
            s.script(Reply(200, Spec.sample(Spec.schemas["SessionLawBatchResponse"]!!.jsonObject).toString()))
            client(s).sessionLaws.getBatchAll((1..201).map { "s$it" }, jurisdiction = "tx")
            assertEquals(listOf(200, 1), s.requests.map { it.json().jsonObject["ids"]!!.jsonArray.size })
        }
        FakeServer().use { s ->
            val c = client(s)
            assertTrue(c.statutes.resolveBatchAll(emptyList()).isEmpty())
            assertEquals(0, s.requests.size)
        }
    }

    private fun assertNotEqualKeys(s: FakeServer) {
        assertTrue(s.requests[0].header("idempotency-key") != s.requests[1].header("idempotency-key"))
    }
}

class UtilTest {
    @Test
    fun queryEncoding() {
        assertEquals("", encodeQuery(null))
        assertEquals(
            "a=true&b=false&n=3&d=1.5&i=2&since=2026-10-29T01%3A02%3A03Z&day=2026-10-29&k=a&k=b&s=a%20b%26%C3%A9&t=x",
            encodeQuery(
                linkedMapOf(
                    "skip" to null, "a" to true, "b" to false, "n" to 3, "d" to 1.5, "i" to 2.0,
                    "since" to Instant.parse("2026-10-29T01:02:03Z"), "day" to LocalDate.of(2026, 10, 29),
                    "k" to listOf("a", "b"), "s" to "a b&é", "t" to JsonPrimitive("x"),
                ),
            ),
        )
        assertEquals("2026-10-29T01:02:03+05:30", queryText(java.time.OffsetDateTime.parse("2026-10-29T01:02:03+05:30")))
        assertEquals("2026-10-29T01:02:03Z", toJson(java.time.ZonedDateTime.parse("2026-10-29T01:02:03Z")).jsonPrimitive.content)
    }

    @Test
    fun jsonBodiesDropUnsetMembers() {
        val o = body("a" to 1, "b" to null, "c" to listOf("x", 2), "d" to mapOf("e" to true), "f" to 1.5, "g" to JsonNull)
        assertEquals("""{"a":1,"c":["x",2],"d":{"e":true},"f":1.5,"g":null}""", o.toString())
        assertEquals("q", strs(listOf("q")))
        assertNull(strs(null))
        assertEquals(listOf("a", "b"), strs(listOf("a", "b")))
        assertEquals(listOf(1, 2), unique(listOf(1, 2, 1)))
    }

    @Test
    fun idempotencyKeys() {
        assertEquals("k".repeat(16), Idempotency.validate("k".repeat(16)))
        for (bad in listOf("", "short", "k".repeat(256), "has space in key!!", "tab\tin-key-123456", "é".repeat(20))) {
            kotlin.test.assertFailsWith<VaquillException>(bad) { Idempotency.validate(bad) }
        }
        assertEquals(36, Idempotency.newKey().length)
        assertEquals("abcdefgh...", Idempotency.redact("abcdefghijkl"))
        assertEquals("kk", Idempotency.forChunk("kk", 0))
        assertNull(Idempotency.forChunk(null, 3))
    }

    @Test
    fun headersAreCaseInsensitive() {
        val h = Headers.of(mapOf("Content-Type" to listOf("a"), "X-Multi" to listOf("1", "2"), "" to listOf("HTTP/1.1 200")))
        assertEquals("a", h["content-type"])
        assertEquals(listOf("1", "2"), h.getAll("x-MULTI"))
        assertEquals(emptyList(), h.getAll("nope"))
        assertEquals(setOf("content-type", "x-multi"), h.names)
        assertEquals(h, Headers.of("content-type" to "a", "x-multi" to "1").let { Headers.of(h.toMap()) })
        assertEquals(h.hashCode(), Headers.of(h.toMap()).hashCode())
        assertTrue(h.toString().contains("x-multi"))
    }

    @Test
    fun versionMatchesTheBuild() {
        val gradle = java.io.File(System.getProperty("vaquill.root"), "build.gradle.kts").readText()
        assertTrue(gradle.contains("version = \"$SDK_VERSION\""), "SDK_VERSION must equal the Gradle version")
        assertEquals("0.1.0", SDK_VERSION)
    }
}
