package ai.vaquill.sdk.internal;

/** Indirection over sleeping so tests can skip real waits. Internal. */
public interface Sleeper {
    /**
     * Sleeps.
     *
     * @param millis the time to wait
     * @throws InterruptedException when interrupted
     */
    void sleep(long millis) throws InterruptedException;

    /** The real thing. */
    Sleeper SYSTEM = Thread::sleep;
}
