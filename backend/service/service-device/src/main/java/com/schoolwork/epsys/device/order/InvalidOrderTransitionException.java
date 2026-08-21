package com.schoolwork.epsys.device.order;

public class InvalidOrderTransitionException extends RuntimeException {

    public InvalidOrderTransitionException(MaintainOrderStatus current, MaintainOrderEvent event) {
        super("工单不允许从 " + current + " 执行事件 " + event);
    }
}
