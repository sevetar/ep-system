package com.schoolwork.epsys.device.order;

import java.util.Arrays;

public enum MaintainOrderStatus {
    PENDING_APPROVAL("待审批"),
    WAITING_FOR_CLAIM("待领取"),
    IN_PROGRESS("维护中"),
    COMPLETED("已完成"),
    REJECTED("已拒绝");

    private final String databaseValue;

    MaintainOrderStatus(String databaseValue) {
        this.databaseValue = databaseValue;
    }

    public String databaseValue() {
        return databaseValue;
    }

    public static MaintainOrderStatus fromDatabase(Object value) {
        String text = String.valueOf(value);
        if ("已通过".equals(text)) {
            return WAITING_FOR_CLAIM;
        }
        return Arrays.stream(values())
                .filter(status -> status.databaseValue.equals(text))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("未知工单状态: " + text));
    }
}
