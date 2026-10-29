package ai.vaquill.sdk;

import java.lang.System.Logger.Level;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Shared test fixtures. */
final class TestSupport {
    static final String KEY = "vq_key_test_0123456789abcdef";

    static final class Recorder {
        final List<Long> sleeps = Collections.synchronizedList(new ArrayList<Long>());
        final List<String> logs = Collections.synchronizedList(new ArrayList<String>());
    }

    static Vaquill.Builder builder(FakeServer server, Recorder rec) {
        return Vaquill.builder()
                .apiKey(KEY)
                .baseUrl(server.url())
                .sleeper(rec.sleeps::add)
                .logger((Level level, String message) -> rec.logs.add(level + " " + message));
    }

    static Vaquill client(FakeServer server) {
        return builder(server, new Recorder()).build();
    }

    private TestSupport() {}
}
