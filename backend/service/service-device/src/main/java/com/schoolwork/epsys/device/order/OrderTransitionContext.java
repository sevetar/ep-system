package com.schoolwork.epsys.device.order;

import java.util.Date;

public record OrderTransitionContext(
        Integer actorId,
        Integer workerId,
        Date occurredAt,
        Date claimDeadline,
        String repairProcess,
        String solution,
        String rootCause,
        String verificationResult,
        String replacedParts,
        String knowledgeTags) {

    public static OrderTransitionContext approval(Integer approverId, Date occurredAt, Date claimDeadline) {
        return new OrderTransitionContext(approverId, null, occurredAt, claimDeadline,
                null, null, null, null, null, null);
    }

    public static OrderTransitionContext assignment(Integer workerId, Date occurredAt) {
        return new OrderTransitionContext(null, workerId, occurredAt, null,
                null, null, null, null, null, null);
    }

    public static OrderTransitionContext completion(Date occurredAt, String repairProcess, String solution,
                                                     String rootCause, String verificationResult,
                                                     String replacedParts, String knowledgeTags) {
        return new OrderTransitionContext(null, null, occurredAt, null, repairProcess, solution,
                rootCause, verificationResult, replacedParts, knowledgeTags);
    }
}
