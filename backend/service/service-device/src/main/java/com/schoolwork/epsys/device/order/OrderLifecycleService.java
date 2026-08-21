package com.schoolwork.epsys.device.order;

import com.schoolwork.epsys.model.device.MaintainRecord;
import org.springframework.stereotype.Service;

import java.util.EnumMap;
import java.util.List;
import java.util.Map;

@Service
public class OrderLifecycleService {

    private final OrderStateMachine stateMachine;
    private final Map<MaintainOrderEvent, OrderEventHandler> handlers;

    public OrderLifecycleService(OrderStateMachine stateMachine, List<OrderEventHandler> handlers) {
        this.stateMachine = stateMachine;
        this.handlers = new EnumMap<>(MaintainOrderEvent.class);
        for (OrderEventHandler handler : handlers) {
            OrderEventHandler previous = this.handlers.put(handler.supports(), handler);
            if (previous != null) {
                throw new IllegalStateException("重复工单事件处理器: " + handler.supports());
            }
        }
    }

    public MaintainOrderStatus apply(MaintainRecord order, MaintainOrderEvent event,
                                     OrderTransitionContext context) {
        MaintainOrderStatus current = MaintainOrderStatus.fromDatabase(order.getStatus());
        MaintainOrderStatus target = stateMachine.next(current, event);
        OrderEventHandler handler = handlers.get(event);
        if (handler == null) {
            throw new IllegalStateException("缺少工单事件处理器: " + event);
        }
        handler.apply(order, context);
        order.setStatus(target.databaseValue());
        return target;
    }
}
