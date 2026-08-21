package com.schoolwork.epsys.device.service;

/**
 * 抢单过程中数据版本发生变化时抛出的异常，用于回滚领取记录和工单更新。
 */
public class ClaimOrderConflictException extends RuntimeException {

    public ClaimOrderConflictException(String message) {
        super(message);
    }
}
