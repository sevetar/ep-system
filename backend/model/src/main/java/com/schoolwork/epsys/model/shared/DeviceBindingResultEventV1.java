package com.schoolwork.epsys.model.shared;

import java.time.Instant;

public record DeviceBindingResultEventV1(
        String schemaVersion,
        String eventId,
        String requestId,
        String eventType,
        Integer userId,
        Integer deviceId,
        String status,
        String reasonCode,
        Instant occurredAt) {
}
