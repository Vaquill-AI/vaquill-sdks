package ai.vaquill.sdk.internal;

import java.util.concurrent.locks.ReentrantLock;

/** Running total of credits consumed, shared by a client and the clients derived from it. Internal. */
public final class SpendTracker {
    private final Object mutex = new Object();
    private double total;
    private final ReentrantLock serial = new ReentrantLock();

    /** @return credits consumed so far */
    public double total() {
        synchronized (mutex) {
            return total;
        }
    }

    /**
     * Adds to the total.
     *
     * @param credits credits consumed by one call
     */
    public void add(double credits) {
        synchronized (mutex) {
            total += credits;
        }
    }

    /** @return the lock held from guard check to accounting by charged calls when a cap is set */
    public ReentrantLock serialLock() {
        return serial;
    }
}
