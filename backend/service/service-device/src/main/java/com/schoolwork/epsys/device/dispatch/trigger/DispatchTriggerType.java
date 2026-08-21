package com.schoolwork.epsys.device.dispatch.trigger;

public enum DispatchTriggerType {
    CLAIM_TIMEOUT("claim_timeout"),
    URGENT("urgent"),
    MANUAL("manual"),
    OVERLOAD("overload");

    private final String wireValue;

    DispatchTriggerType(String wireValue) {
        this.wireValue = wireValue;
    }

    public String wireValue() {
        return wireValue;
    }
}
