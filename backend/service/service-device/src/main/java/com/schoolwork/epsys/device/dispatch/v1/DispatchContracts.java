package com.schoolwork.epsys.device.dispatch.v1;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.time.OffsetDateTime;
import java.util.List;

/** Versioned HTTP contract shared with the FlowFix Agent. */
public final class DispatchContracts {

    public static final String CONTRACT_VERSION = "dispatch-contract/v1";
    public static final String DEFAULT_TENANT = "default";
    public static final int IDEMPOTENCY_KEY_MAX_LENGTH = 300;
    private static final String NUMERIC_ID = "^[1-9][0-9]{0,9}$";
    private static final String CORRELATION_ID = "^[A-Za-z0-9][A-Za-z0-9._:/-]*$";

    private DispatchContracts() {
    }

    public enum OrderStatus { PENDING_APPROVAL, PENDING_DISPATCH, ASSIGNED, COMPLETED, REJECTED }
    public enum Priority { LOW, NORMAL, HIGH, URGENT }
    public enum ReceiptStatus { ACCEPTED, ALREADY_APPLIED, VERSION_CONFLICT, REJECTED }
    public enum OutcomeStatus { ASSIGNED, PENDING, CONFLICT, FAILED, NOT_FOUND }

    public enum ReasonCode {
        INVALID_REQUEST,
        UNSUPPORTED_CONTRACT_VERSION,
        UNAUTHORIZED,
        FORBIDDEN,
        ORDER_NOT_FOUND,
        WORKER_NOT_FOUND,
        VERSION_CONFLICT,
        ORDER_ALREADY_ASSIGNED,
        IDEMPOTENCY_KEY_CONFLICT,
        ORDER_NOT_ASSIGNABLE,
        WORKER_NOT_ELIGIBLE,
        ORDER_BUSY_RETRYABLE,
        INVALID_ORDER_STATE,
        DEPENDENCY_UNAVAILABLE,
        INTERNAL_ERROR
    }

    public record OrderSnapshotV1(
            String contractVersion, String orderId, String tenantId, String deviceId,
            String maintenanceType, List<String> requiredSkills, Priority priority,
            String region, OrderStatus status, String assignedWorkerId,
            Integer version, OffsetDateTime snapshotAt) {
    }

    public record WorkerSnapshotV1(
            String contractVersion, String workerId, String tenantId, List<String> skills,
            String region, String shiftStatus, boolean available, int currentLoad,
            int capacity, OffsetDateTime snapshotAt) {
    }

    public record AssignmentCommandV1(
            @NotBlank @Size(max = 64) String contractVersion,
            @NotBlank @Size(max = 64) @Pattern(regexp = CORRELATION_ID) String traceId,
            @NotBlank @Size(max = 128) @Pattern(regexp = CORRELATION_ID) String eventId,
            @NotBlank @Size(max = 128) @Pattern(regexp = CORRELATION_ID) String dispatchId,
            @NotBlank @Size(max = IDEMPOTENCY_KEY_MAX_LENGTH)
            @Pattern(regexp = CORRELATION_ID) String idempotencyKey,
            @NotBlank @Size(max = 64) @Pattern(regexp = CORRELATION_ID) String tenantId,
            @NotBlank @Pattern(regexp = NUMERIC_ID) String orderId,
            @NotBlank @Pattern(regexp = NUMERIC_ID) String workerId,
            @NotNull @Min(0) Integer expectedVersion) {
    }

    public record AssignmentReceiptV1(
            String contractVersion, ReceiptStatus receiptStatus, ReasonCode reasonCode,
            String orderId, String workerId, Integer expectedVersion, Integer observedVersion,
            String traceId, String eventId, String dispatchId, String idempotencyKey) {
    }

    public record AssignmentOutcomeV1(
            String contractVersion, OutcomeStatus outcomeStatus, ReasonCode reasonCode,
            String orderId, String assignedWorkerId, OrderStatus orderStatus, Integer version,
            String traceId, String eventId, String dispatchId, String idempotencyKey,
            OffsetDateTime verifiedAt) {
    }

    public record ErrorResponseV1(
            String contractVersion, ReasonCode reasonCode, String message,
            String traceId, OffsetDateTime timestamp) {
    }
}
