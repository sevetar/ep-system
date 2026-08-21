package com.schoolwork.epsys.device.dispatch.v1;

import org.springframework.http.HttpStatus;

import java.util.Locale;

import static com.schoolwork.epsys.device.dispatch.v1.DispatchContracts.*;

final class DispatchValueMapper {

    private DispatchValueMapper() {
    }

    static OrderStatus toOrderStatus(Object rawStatus) {
        String value = rawStatus == null ? "" : rawStatus.toString().trim();
        return switch (value) {
            case "待审批" -> OrderStatus.PENDING_APPROVAL;
            case "已通过", "待领取" -> OrderStatus.PENDING_DISPATCH;
            case "维护中" -> OrderStatus.ASSIGNED;
            case "已完成", "正常" -> OrderStatus.COMPLETED;
            case "已拒绝", "未通过", "已驳回" -> OrderStatus.REJECTED;
            default -> throw new DispatchBusinessException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    ReasonCode.INVALID_ORDER_STATE,
                    "工单状态无法映射到 dispatch-contract/v1");
        };
    }

    static Priority toPriority(String rawPriority) {
        if (rawPriority == null || rawPriority.isBlank()) {
            return Priority.NORMAL;
        }
        try {
            return Priority.valueOf(rawPriority.trim().toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException ex) {
            throw new DispatchBusinessException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    ReasonCode.INVALID_REQUEST,
                    "工单优先级不受 dispatch-contract/v1 支持");
        }
    }

    static String normalizeCode(Object rawValue, String fallback) {
        if (rawValue == null || rawValue.toString().isBlank()) {
            return fallback;
        }
        return rawValue.toString().trim().toUpperCase(Locale.ROOT)
                .replaceAll("[^A-Z0-9]+", "_")
                .replaceAll("^_+|_+$", "");
    }
}
