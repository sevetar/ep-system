package com.schoolwork.epsys.device.order;

import com.schoolwork.epsys.model.device.MaintainRecord;
import org.springframework.stereotype.Component;

@Component
public class RejectOrderEventHandler implements OrderEventHandler {

    @Override
    public MaintainOrderEvent supports() {
        return MaintainOrderEvent.REJECT;
    }

    @Override
    public void apply(MaintainRecord order, OrderTransitionContext context) {
        order.setApprovalId(context.actorId());
        order.setApprovalTime(context.occurredAt());
        order.setClaimDeadline(null);
    }
}
