package com.schoolwork.epsys.model.shared;

import java.time.Instant;

public record DeviceBindingRequestedEventV1(
        String schemaVersion,
        String eventId,
        String requestId,
        String eventType,
        Integer userId,
        Integer deviceId,
        Instant occurredAt) {
}
