package com.schoolwork.epsys.device.dispatch.v1;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.schoolwork.epsys.device.mapper.DispatchAssignmentMapper;
import com.schoolwork.epsys.device.mapper.MaintainOrderClaimMapper;
import com.schoolwork.epsys.device.mapper.MaintainRecordMapper;
import com.schoolwork.epsys.device.mapper.RepairmanDispatchProfileMapper;
import com.schoolwork.epsys.model.device.Deviceinstance;
import com.schoolwork.epsys.model.device.DispatchAssignment;
import com.schoolwork.epsys.model.device.MaintainOrderClaim;
import com.schoolwork.epsys.model.device.MaintainRecord;
import com.schoolwork.epsys.model.device.RepairmanDispatchProfile;
import com.schoolwork.epsys.device.order.MaintainOrderEvent;
import com.schoolwork.epsys.device.order.OrderLifecycleService;
import com.schoolwork.epsys.device.order.OrderStateMachine;
import com.schoolwork.epsys.device.order.OrderTransitionContext;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Date;
import java.util.List;

import static com.schoolwork.epsys.device.dispatch.v1.DispatchContracts.*;
import static com.schoolwork.epsys.device.dispatch.v1.DispatchQueryService.tenant;
import static com.schoolwork.epsys.device.dispatch.v1.DispatchValueMapper.*;

@Service
public class DispatchTransactionService {

    private final MaintainRecordMapper maintainRecordMapper;
    private final MaintainOrderClaimMapper claimMapper;
    private final RepairmanDispatchProfileMapper profileMapper;
    private final DispatchAssignmentMapper assignmentMapper;
    private final com.schoolwork.epsys.device.mapper.DeviceinstanceMapper deviceinstanceMapper;
    private final OrderStateMachine stateMachine;
    private final OrderLifecycleService lifecycleService;

    public DispatchTransactionService(MaintainRecordMapper maintainRecordMapper,
                                      MaintainOrderClaimMapper claimMapper,
                                      RepairmanDispatchProfileMapper profileMapper,
                                      DispatchAssignmentMapper assignmentMapper,
                                      com.schoolwork.epsys.device.mapper.DeviceinstanceMapper deviceinstanceMapper,
                                      OrderStateMachine stateMachine,
                                      OrderLifecycleService lifecycleService) {
        this.maintainRecordMapper = maintainRecordMapper;
        this.claimMapper = claimMapper;
        this.profileMapper = profileMapper;
        this.assignmentMapper = assignmentMapper;
        this.deviceinstanceMapper = deviceinstanceMapper;
        this.stateMachine = stateMachine;
        this.lifecycleService = lifecycleService;
    }

    @Transactional
    public AssignmentReceiptV1 assign(AssignmentCommandV1 command, String commandHash) {
        DispatchAssignment previous = findByIdempotencyKey(command.idempotencyKey());
        if (previous != null) {
            return replay(previous, command, commandHash);
        }
        DispatchAssignment sameDispatch = findByDispatchId(command.dispatchId());
        if (sameDispatch != null) {
            return replay(sameDispatch, command, commandHash);
        }

        Integer orderId = Integer.valueOf(command.orderId());
        Integer workerId = Integer.valueOf(command.workerId());
        MaintainRecord order = maintainRecordMapper.selectById(orderId);
        if (order == null) {
            return rejectAndPersist(command, commandHash, ReceiptStatus.REJECTED,
                    ReasonCode.ORDER_NOT_FOUND, null);
        }
        if (!command.tenantId().equals(tenant(order))) {
            return rejectAndPersist(command, commandHash, ReceiptStatus.REJECTED,
                    ReasonCode.ORDER_NOT_FOUND, order.getVersion());
        }
        OrderStatus orderStatus = toOrderStatus(order.getStatus());
        if (order.getMiantainId() != null || orderStatus == OrderStatus.ASSIGNED) {
            return rejectAndPersist(command, commandHash, ReceiptStatus.REJECTED,
                    ReasonCode.ORDER_ALREADY_ASSIGNED, order.getVersion());
        }
        if (!command.expectedVersion().equals(order.getVersion())) {
            return rejectAndPersist(command, commandHash, ReceiptStatus.VERSION_CONFLICT,
                    ReasonCode.VERSION_CONFLICT, order.getVersion());
        }
        if (!stateMachine.canTransition(order.getStatus(), MaintainOrderEvent.AUTO_ASSIGN)) {
            return rejectAndPersist(command, commandHash, ReceiptStatus.REJECTED,
                    ReasonCode.ORDER_NOT_ASSIGNABLE, order.getVersion());
        }

        ReasonCode workerFailure = workerEligibilityFailure(workerId, command.tenantId(), order);
        if (workerFailure != null) {
            return rejectAndPersist(command, commandHash, ReceiptStatus.REJECTED,
                    workerFailure, order.getVersion());
        }

        lifecycleService.apply(order, MaintainOrderEvent.AUTO_ASSIGN,
                OrderTransitionContext.assignment(workerId, new Date()));

        int updated = maintainRecordMapper.assignIfVersionMatches(
                orderId, workerId, command.tenantId(), command.expectedVersion());
        if (updated != 1) {
            MaintainRecord observed = maintainRecordMapper.selectById(orderId);
            ReasonCode reason = observed != null && observed.getMiantainId() != null
                    ? ReasonCode.ORDER_ALREADY_ASSIGNED : ReasonCode.VERSION_CONFLICT;
            ReceiptStatus status = reason == ReasonCode.VERSION_CONFLICT
                    ? ReceiptStatus.VERSION_CONFLICT : ReceiptStatus.REJECTED;
            return rejectAndPersist(command, commandHash, status, reason,
                    observed == null ? null : observed.getVersion());
        }

        MaintainOrderClaim claim = new MaintainOrderClaim();
        claim.setOrderId(orderId);
        claim.setRepairmanId(workerId);
        claim.setRequestId(command.idempotencyKey());
        claim.setClaimedAt(new Date());
        claimMapper.insert(claim);

        int resultVersion = command.expectedVersion() + 1;
        DispatchAssignment assignment = newAssignment(command, commandHash,
                ReceiptStatus.ACCEPTED, null, resultVersion);
        assignmentMapper.insert(assignment);
        return receipt(command, ReceiptStatus.ACCEPTED, null, resultVersion);
    }

    private ReasonCode workerEligibilityFailure(Integer workerId, String tenantId, MaintainRecord order) {
        RepairmanDispatchProfile profile = profileMapper.selectById(workerId);
        if (profile == null) {
            return ReasonCode.WORKER_NOT_FOUND;
        }
        if (!tenantId.equals(profile.getTenantId())
                || !Boolean.TRUE.equals(profile.getActive())
                || !Boolean.TRUE.equals(profile.getAvailable())
                || !"ON_DUTY".equals(profile.getShiftStatus())) {
            return ReasonCode.WORKER_NOT_ELIGIBLE;
        }
        int currentLoad = maintainRecordMapper.countActiveOrders(workerId);
        if (profile.getCapacity() == null || profile.getCapacity() <= 0 || currentLoad >= profile.getCapacity()) {
            return ReasonCode.WORKER_NOT_ELIGIBLE;
        }
        Deviceinstance device = deviceinstanceMapper.selectById(order.getDeviceId());
        if (device == null) {
            throw new DispatchBusinessException(HttpStatus.FAILED_DEPENDENCY,
                    ReasonCode.DEPENDENCY_UNAVAILABLE, "工单关联设备不存在");
        }
        String orderRegion = normalizeCode(device.getLocation(), "UNKNOWN");
        String requiredSkill = normalizeCode(order.getMaintenanceType(), "GENERAL");
        List<String> workerSkills = profileMapper.selectSkills(workerId);
        if (!orderRegion.equals(normalizeCode(profile.getRegionCode(), "UNKNOWN"))
                || !workerSkills.contains(requiredSkill)) {
            return ReasonCode.WORKER_NOT_ELIGIBLE;
        }
        return null;
    }

    private AssignmentReceiptV1 rejectAndPersist(AssignmentCommandV1 command, String commandHash,
                                                  ReceiptStatus status, ReasonCode reasonCode,
                                                  Integer observedVersion) {
        assignmentMapper.insert(newAssignment(command, commandHash, status, reasonCode, observedVersion));
        return receipt(command, status, reasonCode, observedVersion);
    }

    private DispatchAssignment newAssignment(AssignmentCommandV1 command, String commandHash,
                                               ReceiptStatus status, ReasonCode reasonCode,
                                               Integer resultVersion) {
        DispatchAssignment assignment = new DispatchAssignment();
        assignment.setTenantId(command.tenantId());
        assignment.setOrderId(Integer.valueOf(command.orderId()));
        assignment.setWorkerId(Integer.valueOf(command.workerId()));
        assignment.setIdempotencyKey(command.idempotencyKey());
        assignment.setEventId(command.eventId());
        assignment.setDispatchId(command.dispatchId());
        assignment.setTraceId(command.traceId());
        assignment.setExpectedVersion(command.expectedVersion());
        assignment.setResultVersion(resultVersion);
        assignment.setCommandHash(commandHash);
        assignment.setReceiptStatus(status.name());
        assignment.setReasonCode(reasonCode == null ? null : reasonCode.name());
        Date now = new Date();
        assignment.setCreatedAt(now);
        assignment.setUpdatedAt(now);
        return assignment;
    }

    private AssignmentReceiptV1 replay(DispatchAssignment previous, AssignmentCommandV1 command,
                                        String commandHash) {
        if (!previous.getCommandHash().equals(commandHash)) {
            return receipt(command, ReceiptStatus.REJECTED,
                    ReasonCode.IDEMPOTENCY_KEY_CONFLICT, previous.getResultVersion());
        }
        ReceiptStatus oldStatus = ReceiptStatus.valueOf(previous.getReceiptStatus());
        ReceiptStatus replayStatus = oldStatus == ReceiptStatus.ACCEPTED
                ? ReceiptStatus.ALREADY_APPLIED : oldStatus;
        ReasonCode reason = previous.getReasonCode() == null
                ? null : ReasonCode.valueOf(previous.getReasonCode());
        return receipt(command, replayStatus, reason, previous.getResultVersion());
    }

    private AssignmentReceiptV1 receipt(AssignmentCommandV1 command, ReceiptStatus status,
                                         ReasonCode reasonCode, Integer observedVersion) {
        return new AssignmentReceiptV1(CONTRACT_VERSION, status, reasonCode,
                command.orderId(), command.workerId(), command.expectedVersion(), observedVersion,
                command.traceId(), command.eventId(), command.dispatchId(), command.idempotencyKey());
    }

    private DispatchAssignment findByIdempotencyKey(String idempotencyKey) {
        return assignmentMapper.selectOne(Wrappers.<DispatchAssignment>lambdaQuery()
                .eq(DispatchAssignment::getIdempotencyKey, idempotencyKey));
    }

    private DispatchAssignment findByDispatchId(String dispatchId) {
        return assignmentMapper.selectOne(Wrappers.<DispatchAssignment>lambdaQuery()
                .eq(DispatchAssignment::getDispatchId, dispatchId));
    }
}
