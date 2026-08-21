package com.schoolwork.epsys.device.order;

import com.schoolwork.epsys.model.device.MaintainRecord;
import org.junit.jupiter.api.Test;

import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class OrderStateMachineTest {

    private final OrderStateMachine stateMachine = new OrderStateMachine();
    private final OrderLifecycleService lifecycle = new OrderLifecycleService(stateMachine, List.of(
            new ApproveOrderEventHandler(),
            new RejectOrderEventHandler(),
            new ManualClaimOrderEventHandler(),
            new AutoAssignOrderEventHandler(),
            new CompleteOrderEventHandler()));

    @Test
    void validLifecycleUsesTheHandlerForEachEvent() {
        MaintainRecord order = new MaintainRecord();
        order.setStatus("待审批");
        Date approvedAt = new Date();
        Date deadline = new Date(approvedAt.getTime() + 60_000);

        assertEquals(MaintainOrderStatus.WAITING_FOR_CLAIM,
                lifecycle.apply(order, MaintainOrderEvent.APPROVE,
                        OrderTransitionContext.approval(10, approvedAt, deadline)));
        assertEquals("待领取", order.getStatus());
        assertEquals(10, order.getApprovalId());
        assertEquals(deadline, order.getClaimDeadline());

        assertEquals(MaintainOrderStatus.IN_PROGRESS,
                lifecycle.apply(order, MaintainOrderEvent.MANUAL_CLAIM,
                        OrderTransitionContext.assignment(20, new Date())));
        assertEquals("维护中", order.getStatus());
        assertEquals(20, order.getMiantainId());

        assertEquals(MaintainOrderStatus.COMPLETED,
                lifecycle.apply(order, MaintainOrderEvent.COMPLETE,
                        OrderTransitionContext.completion(new Date(), "检测", "更换", "老化",
                                "通过", "电容", "硬件")));
        assertEquals("已完成", order.getStatus());
        assertEquals("更换", order.getSolution());
        assertNotNull(order.getEndTime());
    }

    @Test
    void legacyApprovedStatusIsCompatibleWithClaimTransition() {
        assertTrue(stateMachine.canTransition("已通过", MaintainOrderEvent.AUTO_ASSIGN));
        assertEquals(MaintainOrderStatus.IN_PROGRESS,
                stateMachine.next(MaintainOrderStatus.fromDatabase("已通过"), MaintainOrderEvent.AUTO_ASSIGN));
    }

    @Test
    void illegalTransitionIsRejectedBeforeBusinessFieldsAreChanged() {
        MaintainRecord order = new MaintainRecord();
        order.setStatus("待审批");

        assertThrows(InvalidOrderTransitionException.class,
                () -> lifecycle.apply(order, MaintainOrderEvent.COMPLETE,
                        OrderTransitionContext.completion(new Date(), "x", "x", "x", "x", "x", "x")));
        assertEquals("待审批", order.getStatus());
        assertNull(order.getEndTime());
    }
}
