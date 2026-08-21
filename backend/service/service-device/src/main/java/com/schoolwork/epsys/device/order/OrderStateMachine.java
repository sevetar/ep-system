package com.schoolwork.epsys.device.order;

import org.springframework.stereotype.Component;

import java.util.Map;

@Component
public class OrderStateMachine {

    private static final Map<MaintainOrderStatus, Map<MaintainOrderEvent, MaintainOrderStatus>> TRANSITIONS = Map.of(
            MaintainOrderStatus.PENDING_APPROVAL, Map.of(
                    MaintainOrderEvent.APPROVE, MaintainOrderStatus.WAITING_FOR_CLAIM,
                    MaintainOrderEvent.REJECT, MaintainOrderStatus.REJECTED),
            MaintainOrderStatus.WAITING_FOR_CLAIM, Map.of(
                    MaintainOrderEvent.MANUAL_CLAIM, MaintainOrderStatus.IN_PROGRESS,
                    MaintainOrderEvent.AUTO_ASSIGN, MaintainOrderStatus.IN_PROGRESS),
            MaintainOrderStatus.IN_PROGRESS, Map.of(
                    MaintainOrderEvent.COMPLETE, MaintainOrderStatus.COMPLETED));

    public MaintainOrderStatus next(MaintainOrderStatus current, MaintainOrderEvent event) {
        MaintainOrderStatus target = TRANSITIONS.getOrDefault(current, Map.of()).get(event);
        if (target == null) {
            throw new InvalidOrderTransitionException(current, event);
        }
        return target;
    }

    public boolean canTransition(Object databaseStatus, MaintainOrderEvent event) {
        try {
            next(MaintainOrderStatus.fromDatabase(databaseStatus), event);
            return true;
        } catch (IllegalArgumentException | InvalidOrderTransitionException exception) {
            return false;
        }
    }
}
