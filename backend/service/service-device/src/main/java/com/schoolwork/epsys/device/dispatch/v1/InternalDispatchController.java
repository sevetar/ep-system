package com.schoolwork.epsys.device.dispatch.v1;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.slf4j.MDC;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

import static com.schoolwork.epsys.device.dispatch.v1.DispatchContracts.*;

@Validated
@RestController
@RequestMapping("/internal/dispatch/v1")
public class InternalDispatchController {

    private final DispatchQueryService queryService;
    private final DispatchCommandService commandService;

    public InternalDispatchController(DispatchQueryService queryService,
                                      DispatchCommandService commandService) {
        this.queryService = queryService;
        this.commandService = commandService;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        return ResponseEntity.ok(Map.of("status", "UP", "contractVersion", CONTRACT_VERSION));
    }

    @GetMapping("/orders/{orderId}/snapshot")
    public ResponseEntity<OrderSnapshotV1> orderSnapshot(
            @RequestHeader(value = "X-Trace-Id", required = false) @Size(max = 64) String traceId,
            @PathVariable @Pattern(regexp = "^[1-9][0-9]{0,9}$") String orderId) {
        return withTrace(traceId, () -> ResponseEntity.ok(
                queryService.getOrderSnapshot(parseId(orderId))));
    }

    @GetMapping("/orders/{orderId}/workers")
    public ResponseEntity<?> eligibleWorkers(
            @RequestHeader(value = "X-Trace-Id", required = false) @Size(max = 64) String traceId,
            @PathVariable @Pattern(regexp = "^[1-9][0-9]{0,9}$") String orderId) {
        return withTrace(traceId, () -> ResponseEntity.ok(Map.of(
                "contractVersion", CONTRACT_VERSION,
                "workers", queryService.getEligibleWorkers(parseId(orderId)))));
    }

    @PostMapping("/assignments")
    public ResponseEntity<AssignmentReceiptV1> assign(
            @RequestHeader(value = "Idempotency-Key") @Size(max = IDEMPOTENCY_KEY_MAX_LENGTH) String headerKey,
            @Valid @RequestBody AssignmentCommandV1 command) {
        if (!headerKey.equals(command.idempotencyKey())) {
            throw new DispatchBusinessException(HttpStatus.BAD_REQUEST,
                    ReasonCode.INVALID_REQUEST, "Header 与 body 的 Idempotency-Key 必须一致");
        }
        return withTrace(command.traceId(), () -> {
            AssignmentReceiptV1 receipt = commandService.assign(command);
            return ResponseEntity.status(httpStatus(receipt)).body(receipt);
        });
    }

    @GetMapping("/assignments/{dispatchId}/outcome")
    public ResponseEntity<AssignmentOutcomeV1> outcome(
            @RequestHeader(value = "X-Trace-Id", required = false) @Size(max = 64) String traceId,
            @PathVariable @Size(max = 128) String dispatchId) {
        return withTrace(traceId, () -> ResponseEntity.ok(queryService.getOutcome(dispatchId)));
    }

    private HttpStatus httpStatus(AssignmentReceiptV1 receipt) {
        if (receipt.receiptStatus() == ReceiptStatus.ACCEPTED
                || receipt.receiptStatus() == ReceiptStatus.ALREADY_APPLIED) {
            return HttpStatus.OK;
        }
        return switch (receipt.reasonCode()) {
            case ORDER_NOT_FOUND, WORKER_NOT_FOUND -> HttpStatus.NOT_FOUND;
            case ORDER_NOT_ASSIGNABLE, WORKER_NOT_ELIGIBLE, INVALID_ORDER_STATE ->
                    HttpStatus.UNPROCESSABLE_ENTITY;
            case VERSION_CONFLICT, ORDER_ALREADY_ASSIGNED, IDEMPOTENCY_KEY_CONFLICT,
                    ORDER_BUSY_RETRYABLE -> HttpStatus.CONFLICT;
            default -> HttpStatus.BAD_REQUEST;
        };
    }

    private <T> T withTrace(String traceId, java.util.function.Supplier<T> action) {
        String previous = MDC.get("traceId");
        if (traceId != null && !traceId.isBlank()) {
            MDC.put("traceId", traceId);
        }
        try {
            return action.get();
        } catch (DispatchBusinessException ex) {
            throw ex.withTraceId(traceId);
        } finally {
            if (previous == null) {
                MDC.remove("traceId");
            } else {
                MDC.put("traceId", previous);
            }
        }
    }

    private Integer parseId(String id) {
        try {
            return Integer.valueOf(id);
        } catch (NumberFormatException ex) {
            throw new DispatchBusinessException(HttpStatus.BAD_REQUEST,
                    ReasonCode.INVALID_REQUEST, "ID 超出 Java Integer 范围");
        }
    }
}
