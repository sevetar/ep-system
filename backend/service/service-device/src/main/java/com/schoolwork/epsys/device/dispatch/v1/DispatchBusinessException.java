package com.schoolwork.epsys.device.dispatch.v1;

import org.springframework.http.HttpStatus;

import static com.schoolwork.epsys.device.dispatch.v1.DispatchContracts.ReasonCode;

public class DispatchBusinessException extends RuntimeException {
    private final HttpStatus httpStatus;
    private final ReasonCode reasonCode;
    private String traceId;

    public DispatchBusinessException(HttpStatus httpStatus, ReasonCode reasonCode, String message) {
        super(message);
        this.httpStatus = httpStatus;
        this.reasonCode = reasonCode;
    }

    public HttpStatus getHttpStatus() { return httpStatus; }
    public ReasonCode getReasonCode() { return reasonCode; }
    public String getTraceId() { return traceId; }

    public DispatchBusinessException withTraceId(String traceId) {
        this.traceId = traceId;
        return this;
    }
}
