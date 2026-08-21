package com.schoolwork.epsys.device.service;

/**
 * 维修人员领取维护工单的业务结果。
 */
public enum ClaimOrderResult {
    SUCCESS,
    IDEMPOTENT_SUCCESS,
    ORDER_NOT_FOUND,
    ORDER_NOT_CLAIMABLE,
    ORDER_ALREADY_CLAIMED,
    IDEMPOTENCY_KEY_CONFLICT
}
