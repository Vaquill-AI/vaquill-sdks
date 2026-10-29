package ai.vaquill.sdk

import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.Assumptions.assumeTrue
import org.junit.jupiter.api.Tag
import kotlin.test.Test
import kotlin.test.assertTrue

/**
 * Tiny, credit-capped smoke test against the production API. Excluded from `test`/`build`.
 * Run: `VAQUILL_API_KEY=... ./gradlew liveSmoke -PliveSmoke`. It never prints the key.
 */
@Tag("live")
class LiveSmokeTest {
    @Test
    fun freeAndTinyChargedCallsWork() = runBlocking<Unit> {
        assumeTrue(!System.getenv("VAQUILL_API_KEY").isNullOrBlank(), "VAQUILL_API_KEY is not set")
        VaquillClient { maxCredits = 5.0 }.use { c ->
            val balance = c.withResponse { credits.balance() }
            assertTrue(balance.statusCode == 200)
            assertTrue(balance.requestId != null || balance.headers.names.isNotEmpty())

            val pricing = c.pricing.get()
            assertTrue(pricing.costs.isNotEmpty())

            val boards = c.boards.list(limit = 1)
            assertTrue(boards.data.boards.size <= 1)

            // One charged call (about 1 credit), capped client-side at 5.
            val count = c.withResponse { statutes.count(state = "wa") }
            assertTrue(count.data.count >= 0)
            assertTrue((count.creditsConsumed ?: 0.0) <= 2.0, "unexpectedly expensive: ${count.creditsConsumed}")
            assertTrue(c.creditsSpent <= 2.0)
            println("live smoke ok: count credits=${count.creditsConsumed} spent=${c.creditsSpent}")
        }
    }
}
