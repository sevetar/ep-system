package com.schoolwork.epsys.device.dispatch.v1;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

import static com.schoolwork.epsys.device.dispatch.v1.DispatchContracts.AssignmentCommandV1;

final class DispatchCommandHasher {

    private DispatchCommandHasher() {
    }

    static String hash(AssignmentCommandV1 command) {
        String canonical = String.join("\n",
                command.contractVersion(), command.eventId(), command.dispatchId(),
                command.idempotencyKey(), command.tenantId(), command.orderId(), command.workerId(),
                command.expectedVersion().toString());
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(canonical.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
    }
}
