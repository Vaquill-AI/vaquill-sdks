package ai.vaquill.sdk

import ai.vaquill.sdk.resources.SearchFilters
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.serializer
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class OperationsTest {
    private class Case(val id: String, val body: String? = null, val call: suspend (VaquillClient) -> Any?)

    private val act = "a/b c" // encodes to a%2Fb%20c
    private val cases: List<Case> = listOf(
        Case("get_pricing") { it.pricing.get(region = "US") },
        Case("list_boards") { it.boards.list(corpusType = "usc", limit = 5) },
        Case("get_credit_balance") { it.credits.balance() },
        Case("get_session_laws_batch", """{"ids":["a","b"]}""") { it.sessionLaws.getBatch(listOf("a", "b")) },
        Case("get_session_law_changes") { it.sessionLaws.changes(sinceId = 3) },
        Case("list_session_laws") { it.sessionLaws.list("tx") },
        Case("search_session_laws", """{"query":"q"}""") { it.sessionLaws.search("q") },
        Case("get_session_law") { it.sessionLaws.get("sl/1") },
        Case("get_session_law_body") { it.sessionLaws.getBody("sl/1") },
        Case("get_session_law_versions") { it.sessionLaws.versions("sl/1") },
        Case("count_statute_sections", """{"state":"tx"}""") { it.statutes.count(state = "tx") },
        Case("list_statutes_coverage") { it.statutes.coverage() },
        Case("list_statute_divisions") { it.statutes.divisions("usc") },
        Case("extract_statute_citations", """{"text":"t"}""") { it.statutes.extractCitations("t") },
        Case("get_part_rulemaking") { it.statutes.partRulemaking(12, "1026") },
        Case("resolve_statute_citation") { it.statutes.resolve("42 U.S.C. 1983") },
        Case("resolve_statute_citations_batch", """{"citations":["c"]}""") { it.statutes.resolveBatch(listOf("c")) },
        Case("search_statutes", """{"query":"q"}""") { it.statutes.search("q") },
        Case("get_section") { it.statutes.getSection(act) },
        Case("get_section_body") { it.statutes.getSectionBody(act) },
        Case("get_section_changes") { it.statutes.sectionChanges(act) },
        Case("get_section_cited_by") { it.statutes.citedBy(act) },
        Case("get_section_cross_state") { it.statutes.crossState(act) },
        Case("get_section_definitions") { it.statutes.definitions(act) },
        Case("get_section_enactments") { it.statutes.enactments(act) },
        Case("get_section_neighbors") { it.statutes.neighbors(act) },
        Case("get_section_rulemaking") { it.statutes.sectionRulemaking(act) },
        Case("get_sections_batch", """{"actIds":["x"]}""") { it.statutes.getSectionsBatch(listOf("x")) },
        Case("list_watches") { it.watches.list() },
        Case("create_watch", """{"corpusType":"usc"}""") { it.watches.create("usc") },
        Case("delete_watch") { it.watches.delete("w 1") },
        Case("update_watch", """{"isActive":false}""") { it.watches.update("w 1", isActive = false) },
        Case("list_watch_changes") { it.watches.changes("w 1") },
        Case("get_watch_change_diff") { it.watches.changeDiff("w 1", 7) },
        Case("list_watch_deliveries") { it.watches.deliveries("w 1") },
        Case("test_watch") { it.watches.test("w 1") },
    )

    private fun expectedPath(path: String): String = path
        .replace("{act_id}", "a%2Fb%20c").replace("{session_law_id}", "sl%2F1")
        .replace("{watch_id}", "w%201").replace("{change_id}", "7")
        .replace("{title}", "12").replace("{part}", "1026")

    @Test
    fun everySpecOperationHasAMethodAndIsExercised() {
        assertEquals(36, Spec.operations.size, "the contract has 36 operations")
        assertEquals(Spec.operations.map { it.id }.sorted(), cases.map { it.id }.sorted())
    }

    @Test
    fun oneRequestPerOperationMatchesTheContract() = runBlocking<Unit> {
        FakeServer().use { server ->
            val c = client(server)
            for (case in cases) {
                val op = Spec.operations.single { it.id == case.id }
                server.requests.clear()
                val status = op.status.toInt()
                val body = if (op.response == null) "" else Json.encodeToString(kotlinx.serialization.json.JsonElement.serializer(), Spec.sample(op.response))
                server.script(Reply(status, body))
                case.call(c)
                assertEquals(1, server.requests.size, case.id)
                val r = server.requests.single()
                assertEquals(op.method, r.method, case.id)
                assertEquals(expectedPath(op.path), r.rawPath, case.id)
                assertEquals(op.charged, r.header("idempotency-key") != null, "${case.id}: charged iff the spec declares Idempotency-Key")
                assertEquals("Bearer $TEST_KEY", r.header("authorization"), case.id)
                assertTrue(r.header("user-agent")!!.startsWith("vaquill-kotlin/$SDK_VERSION"), case.id)
                if (case.body != null) {
                    assertEquals(Json.parseToJsonElement(case.body), r.json(), case.id)
                    assertEquals("application/json", r.header("content-type"), case.id)
                } else {
                    assertEquals("", r.body, case.id)
                }
            }
            assertEquals(25, Spec.operations.count { it.charged })
        }
    }

    @Test
    fun everySchemaHasAGeneratedClassWithTheSamePropertiesAndDecodesASample() {
        for ((name, schema) in Spec.schemas) {
            val s = schema.jsonObject
            if (s["enum"] != null) continue // enums are generated as constant holders
            val cls = Class.forName("ai.vaquill.sdk.models.$name")
            val props = s["properties"]?.jsonObject?.keys ?: emptySet()
            if (props.isEmpty()) continue
            val descriptor = serializer(cls).descriptor
            val names = (0 until descriptor.elementsCount).map { descriptor.getElementName(it) }.toSet()
            assertEquals(props, names, "properties of $name drifted from the contract: regenerate the models")
            for (full in listOf(false, true)) {
                val sample = Spec.sample(s, full)
                VaquillJson.decodeFromJsonElement(serializer(cls), sample)
            }
        }
    }

    @Test
    fun pathSegmentsAreValidatedAndEncoded() = runBlocking<Unit> {
        FakeServer().use { server ->
            val c = client(server)
            for (bad in listOf("", ".", "..")) {
                val e = kotlin.runCatching { c.statutes.getSection(bad) }.exceptionOrNull()
                assertTrue(e is IllegalArgumentException, "segment '$bad' must be rejected")
            }
            assertEquals(0, server.requests.size)
            server.script(Reply(200, Json.encodeToString(kotlinx.serialization.json.JsonElement.serializer(), Spec.sample(Spec.operations.single { it.id == "get_section" }.response!!))))
            c.statutes.getSection("100%/é?#")
            assertEquals("/api/v1/us/statutes/section/100%25%2F%C3%A9%3F%23", server.requests.single().rawPath)
        }
    }

    @Test
    fun searchSendsFiltersAndASingleCorpusTypeAsAString() = runBlocking<Unit> {
        FakeServer().use { server ->
            server.script(Reply(200, """{"results":[]}"""))
            val c = client(server)
            runCatching { c.statutes.search("q", SearchFilters(state = "tx", corpusType = listOf("state_statute"), agency = listOf("a", "b"), limit = 3), offset = 6) }
            val body = server.requests.single().json().jsonObject
            assertEquals(JsonPrimitive("state_statute"), body["corpusType"])
            assertEquals(2, (body["agency"] as kotlinx.serialization.json.JsonArray).size)
            assertEquals(JsonPrimitive(6), body["offset"])
        }
    }
}
