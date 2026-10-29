package ai.vaquill.sdk;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** A local HTTP server that records requests and answers from a script. */
final class FakeServer implements AutoCloseable {
    static final class Req {
        String method;
        String path;
        String query;
        String body;
        final Map<String, String> headers = new LinkedHashMap<>();
    }

    static final class Reply {
        int status = 200;
        String body = "{}";
        final Map<String, String> headers = new LinkedHashMap<>();
        boolean drop;
        long delayMillis;

        static Reply json(int status, String body) {
            Reply r = new Reply();
            r.status = status;
            r.body = body;
            return r;
        }

        static Reply dropConnection() {
            Reply r = new Reply();
            r.drop = true;
            return r;
        }

        Reply header(String k, String v) {
            headers.put(k, v);
            return this;
        }
    }

    interface Handler {
        Reply handle(Req request, int index);
    }

    private final HttpServer server;
    private final ExecutorService pool = Executors.newFixedThreadPool(16);
    final List<Req> requests = Collections.synchronizedList(new ArrayList<Req>());
    volatile Handler handler = (r, i) -> Reply.json(200, "{}");

    FakeServer() {
        try {
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        } catch (IOException e) {
            throw new IllegalStateException(e);
        }
        server.setExecutor(pool);
        server.createContext("/", this::serve);
        server.start();
    }

    String url() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    FakeServer reply(Handler h) {
        this.handler = h;
        return this;
    }

    /** Replies from a list in order; the last entry repeats. */
    FakeServer script(Reply... replies) {
        return reply((r, i) -> replies[Math.min(i, replies.length - 1)]);
    }

    private void serve(HttpExchange ex) throws IOException {
        Req r = new Req();
        r.method = ex.getRequestMethod();
        r.path = ex.getRequestURI().getRawPath();
        r.query = ex.getRequestURI().getRawQuery() == null ? "" : ex.getRequestURI().getRawQuery();
        try (InputStream in = ex.getRequestBody()) {
            r.body = new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
        ex.getRequestHeaders().forEach((k, v) -> r.headers.put(k.toLowerCase(Locale.ROOT), v.get(0)));
        int index;
        synchronized (requests) {
            index = requests.size();
            requests.add(r);
        }
        Reply reply = handler.handle(r, index);
        if (reply.delayMillis > 0) {
            try {
                Thread.sleep(reply.delayMillis);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        if (reply.drop) {
            ex.close();
            return;
        }
        byte[] bytes = reply.body.getBytes(StandardCharsets.UTF_8);
        reply.headers.forEach((k, v) -> ex.getResponseHeaders().add(k, v));
        ex.getResponseHeaders().add("Content-Type", "application/json");
        if (reply.status == 204 || bytes.length == 0) {
            ex.sendResponseHeaders(reply.status, -1);
        } else {
            ex.sendResponseHeaders(reply.status, bytes.length);
            try (OutputStream out = ex.getResponseBody()) {
                out.write(bytes);
            }
        }
        ex.close();
    }

    @Override
    public void close() {
        server.stop(0);
        pool.shutdownNow();
    }
}
