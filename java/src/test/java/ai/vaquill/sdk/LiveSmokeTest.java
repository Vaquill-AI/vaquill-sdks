package ai.vaquill.sdk;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import ai.vaquill.sdk.models.ExternalCreditBalanceResponse;
import ai.vaquill.sdk.models.StatuteCountRequest;
import org.junit.jupiter.api.Test;

/**
 * Calls the production API. It is skipped unless {@code -Dvaquill.live=true} (or {@code mvn -Plive test})
 * and {@code VAQUILL_API_KEY} is set. The spend guard caps it at 10 credits and the key is never printed.
 */
class LiveSmokeTest {
    @Test
    void balanceAndOneCount() {
        assumeTrue(Boolean.getBoolean("vaquill.live"), "live smoke test disabled; use -Plive");
        String key = System.getenv("VAQUILL_API_KEY");
        assumeTrue(key != null && !key.trim().isEmpty(), "VAQUILL_API_KEY is not set");
        try (Vaquill client = Vaquill.builder().apiKey(key).maxCredits(10).build()) {
            ExternalCreditBalanceResponse balance = client.credits().balance();
            assertNotNull(balance.getCreditsRemaining());
            Response<ai.vaquill.sdk.models.StatuteCountResponse> counted =
                    client.statutes().countWithResponse(StatuteCountRequest.builder().state("ca").build());
            assertNotNull(counted.getRequestId());
            assertTrue(client.getCreditsSpent() <= 10.0);
            System.out.println("live smoke ok: status=" + counted.getStatusCode() + " requestId=" + counted.getRequestId()
                    + " spent=" + client.getCreditsSpent());
        }
    }
}
