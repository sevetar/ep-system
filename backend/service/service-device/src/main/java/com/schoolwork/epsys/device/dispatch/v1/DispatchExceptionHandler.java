package com.schoolwork.epsys.device.dispatch.v1;

import jakarta.validation.ConstraintViolationException;
import org.slf4j.MDC;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.time.OffsetDateTime;
import java.time.ZoneId;

import static com.schoolwork.epsys.device.dispatch.v1.DispatchContracts.*;

@RestControllerAdvice(assignableTypes = InternalDispatchController.class)
public class DispatchExceptionHandler {

    private static final ZoneId BUSINESS_ZONE = ZoneId.of("Asia/Shanghai");

    @ExceptionHandler(DispatchBusinessException.class)
    public ResponseEntity<ErrorResponseV1> handleBusiness(DispatchBusinessException ex) {
        return ResponseEntity.status(ex.getHttpStatus())
                .body(error(ex.getReasonCode(), ex.getMessage(), ex.getTraceId()));
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, ConstraintViolationException.class,
            HttpMessageNotReadableException.class})
    public ResponseEntity<ErrorResponseV1> handleInvalidRequest(Exception ex) {
        return ResponseEntity.badRequest().body(error(
                ReasonCode.INVALID_REQUEST, "请求不符合 dispatch-contract/v1", null));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponseV1> handleUnexpected(Exception ex) {
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(error(ReasonCode.INTERNAL_ERROR, "内部服务处理失败", null));
    }

    private ErrorResponseV1 error(ReasonCode reasonCode, String message, String explicitTraceId) {
        return new ErrorResponseV1(CONTRACT_VERSION, reasonCode, message,
                explicitTraceId == null ? MDC.get("traceId") : explicitTraceId,
                OffsetDateTime.now(BUSINESS_ZONE));
    }
}
