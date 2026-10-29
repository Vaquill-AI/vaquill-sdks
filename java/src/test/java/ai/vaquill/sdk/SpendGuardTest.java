package ai.vaquill.sdk;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.vaquill.sdk.FakeServer.Reply;
import ai.vaquill.sdk.models.StatuteCountRequest;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class SpendGuardTest {
    private static final StatuteCountRequest COUNT = StatuteCountRequest.builder().build();

    @Test
    void capStopsChargedCallsBeforeTheyAreSent() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(200, "{\"creditsConsumed\":1}"));
            Vaquill c = TestSupport.builder(server, new TestSupport.Recorder()).maxCredits(2).build();
            c.statutes().count(COUNT);
            c.statutes().count(COUNT);
            SpendGuardExceededException e = assertThrows(SpendGuardExceededException.class, () -> c.statutes().count(COUNT));
            assertTrue(e.getMessage().contains("2 of 2"), e.getMessage());
            assertEquals(2, server.requests.size(), "the third call was never sent");
            assertEquals(2.0, c.getCreditsSpent());
            // Free calls are not blocked by the guard.
            c.credits().balance();
            assertEquals(3, server.requests.size());
        }
    }

    @Test
    void zeroCapBlocksEverythingCharged() {
        try (FakeServer server = new FakeServer()) {
            Vaquill c = TestSupport.builder(server, new TestSupport.Recorder()).maxCredits(0).build();
            assertThrows(SpendGuardExceededException.class, () -> c.statutes().count(COUNT));
            assertEquals(0, server.requests.size());
        }
    }

    @Test
    void replaysAndFractionalCreditsAreAccounted() {
        try (FakeServer server = new FakeServer()) {
            Vaquill c = TestSupport.builder(server, new TestSupport.Recorder()).maxCredits(1).build();
            server.script(Reply.json(200, "{\"creditsConsumed\":0.5}"));
            c.statutes().count(COUNT);
            server.script(Reply.json(200, "{\"creditsConsumed\":5}").header("Idempotent-Replayed", "true"));
            c.statutes().count(COUNT);
            assertEquals(0.5, c.getCreditsSpent());
            server.script(Reply.json(200, "{\"creditsConsumed\":0.5}"));
            c.statutes().count(COUNT);
            assertEquals(1.0, c.getCreditsSpent());
            SpendGuardExceededException e = assertThrows(SpendGuardExceededException.class, () -> c.statutes().count(COUNT));
            assertTrue(e.getMessage().contains("1 of 1"));
            server.script(Reply.json(200, "{}"));
            assertEquals(1.0, c.getCreditsSpent());
        }
    }

    @Test
    void capIsExactUnderConcurrency() throws Exception {
        try (FakeServer server = new FakeServer()) {
            Reply slow = Reply.json(200, "{\"creditsConsumed\":1}");
            slow.delayMillis = 15;
            server.script(slow);
            final Vaquill c = TestSupport.builder(server, new TestSupport.Recorder()).maxCredits(5).build();
            ExecutorService pool = Executors.newFixedThreadPool(16);
            AtomicInteger ok = new AtomicInteger();
            AtomicInteger refused = new AtomicInteger();
            List<Future<?>> futures = new ArrayList<>();
            for (int i = 0; i < 40; i++) {
                futures.add(pool.submit(() -> {
                    try {
                        c.statutes().count(COUNT);
                        ok.incrementAndGet();
                    } catch (SpendGuardExceededException e) {
                        refused.incrementAndGet();
                    }
                }));
            }
            for (Future<?> f : futures) {
                f.get();
            }
            pool.shutdown();
            assertEquals(5, ok.get(), "exactly the cap is spent, never more");
            assertEquals(35, refused.get());
            assertEquals(5, server.requests.size());
            assertEquals(5.0, c.getCreditsSpent());
        }
    }

    @Test
    void asyncCallsRespectTheGuardToo() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(200, "{\"creditsConsumed\":1}"));
            Vaquill c = TestSupport.builder(server, new TestSupport.Recorder()).maxCredits(1).build();
            c.statutes().countAsync(COUNT).join();
            java.util.concurrent.CompletionException e = assertThrows(java.util.concurrent.CompletionException.class,
                    () -> c.statutes().countAsync(COUNT).join());
            assertTrue(e.getCause() instanceof SpendGuardExceededException);
            c.close();
        }
    }

    @Test
    void batchHelperStopsPartWayWhenTheGuardIsReached() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(200, "{\"creditsConsumed\":1,\"results\":[]}"));
            Vaquill c = TestSupport.builder(server, new TestSupport.Recorder()).maxCredits(1).build();
            List<String> cites = new ArrayList<>();
            for (int i = 0; i < 1200; i++) {
                cites.add("cite " + i);
            }
            assertThrows(SpendGuardExceededException.class, () -> c.statutes().resolveBatchAll(cites));
            assertEquals(1, server.requests.size(), "the second chunk was not sent");
        }
    }
}
