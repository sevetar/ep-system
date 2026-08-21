package com.schoolwork.epsys.device.order;

import com.schoolwork.epsys.model.device.MaintainRecord;

public interface OrderEventHandler {

    MaintainOrderEvent supports();

    void apply(MaintainRecord order, OrderTransitionContext context);
}
