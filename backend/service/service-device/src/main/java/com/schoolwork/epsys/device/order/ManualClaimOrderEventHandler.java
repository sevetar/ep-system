package com.schoolwork.epsys.device.order;

import com.schoolwork.epsys.model.device.MaintainRecord;
import org.springframework.stereotype.Component;

@Component
public class ManualClaimOrderEventHandler implements OrderEventHandler {

    @Override
    public MaintainOrderEvent supports() {
        return MaintainOrderEvent.MANUAL_CLAIM;
    }

    @Override
    public void apply(MaintainRecord order, OrderTransitionContext context) {
        order.setMiantainId(context.workerId());
    }
}
