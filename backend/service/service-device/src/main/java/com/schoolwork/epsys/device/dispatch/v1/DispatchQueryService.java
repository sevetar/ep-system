package com.schoolwork.epsys.device.dispatch.v1;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.schoolwork.epsys.device.mapper.DeviceinstanceMapper;
import com.schoolwork.epsys.device.mapper.DispatchAssignmentMapper;
import com.schoolwork.epsys.device.mapper.MaintainRecordMapper;
import com.schoolwork.epsys.device.mapper.RepairmanDispatchProfileMapper;
import com.schoolwork.epsys.model.device.Deviceinstance;
import com.schoolwork.epsys.model.device.DispatchAssignment;
import com.schoolwork.epsys.model.device.MaintainRecord;
import com.schoolwork.epsys.model.device.RepairmanDispatchProfile;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;

import static com.schoolwork.epsys.device.dispatch.v1.DispatchContracts.*;
import static com.schoolwork.epsys.device.dispatch.v1.DispatchValueMapper.*;

@Service
public class DispatchQueryService {

    private static final ZoneId BUSINESS_ZONE = ZoneId.of("Asia/Shanghai");

    private final MaintainRecordMapper maintainRecordMapper;
    private final DeviceinstanceMapper deviceinstanceMapper;
    private final RepairmanDispatchProfileMapper profileMapper;
    private final DispatchAssignmentMapper assignmentMapper;

    public DispatchQueryService(MaintainRecordMapper maintainRecordMapper,
                                DeviceinstanceMapper deviceinstanceMapper,
                                RepairmanDispatchProfileMapper profileMapper,
                                DispatchAssignmentMapper assignmentMapper) {
        this.maintainRecordMapper = maintainRecordMapper;
        this.deviceinstanceMapper = deviceinstanceMapper;
        this.profileMapper = profileMapper;
        this.assignmentMapper = assignmentMapper;
    }

    public OrderSnapshotV1 getOrderSnapshot(Integer orderId) {
        MaintainRecord order = requireOrder(orderId);
        Deviceinstance device = deviceinstanceMapper.selectById(order.getDeviceId());
        if (device == null) {
            throw new DispatchBusinessException(HttpStatus.FAILED_DEPENDENCY,
                    ReasonCode.DEPENDENCY_UNAVAILABLE, "工单关联设备不存在");
        }
        String maintenanceType = normalizeCode(order.getMaintenanceType(), "GENERAL");
        return new OrderSnapshotV1(
                CONTRACT_VERSION,
                order.getId().toString(),
                tenant(order),
                order.getDeviceId().toString(),
                maintenanceType,
                List.of(maintenanceType),
                toPriority(order.getPriority()),
                normalizeCode(device.getLocation(), "UNKNOWN"),
                toOrderStatus(order.getStatus()),
                order.getMiantainId() == null ? null : order.getMiantainId().toString(),
                order.getVersion(),
                OffsetDateTime.now(BUSINESS_ZONE));
    }

    public List<WorkerSnapshotV1> getEligibleWorkers(Integer orderId) {
        OrderSnapshotV1 order = getOrderSnapshot(orderId);
        OffsetDateTime snapshotAt = OffsetDateTime.now(BUSINESS_ZONE);
        List<RepairmanDispatchProfile> profiles = profileMapper.selectList(
                Wrappers.<RepairmanDispatchProfile>lambdaQuery()
                        .eq(RepairmanDispatchProfile::getTenantId, order.tenantId())
                        .eq(RepairmanDispatchProfile::getActive, true)
                        .eq(RepairmanDispatchProfile::getAvailable, true)
                        .eq(RepairmanDispatchProfile::getShiftStatus, "ON_DUTY")
                        .orderByAsc(RepairmanDispatchProfile::getWorkerId));

        List<WorkerSnapshotV1> result = new ArrayList<>();
        for (RepairmanDispatchProfile profile : profiles) {
            int currentLoad = maintainRecordMapper.countActiveOrders(profile.getWorkerId());
            List<String> skills = profileMapper.selectSkills(profile.getWorkerId());
            boolean regionMatches = order.region().equals(profile.getRegionCode());
            boolean skillsMatch = skills.containsAll(order.requiredSkills());
            if (currentLoad < profile.getCapacity() && regionMatches && skillsMatch) {
                result.add(toWorkerSnapshot(profile, skills, currentLoad, snapshotAt));
            }
        }
        return result;
    }

    public AssignmentOutcomeV1 getOutcome(String dispatchId) {
        DispatchAssignment assignment = assignmentMapper.selectOne(
                Wrappers.<DispatchAssignment>lambdaQuery()
                        .eq(DispatchAssignment::getDispatchId, dispatchId));
        if (assignment == null) {
            return new AssignmentOutcomeV1(CONTRACT_VERSION, OutcomeStatus.NOT_FOUND,
                    ReasonCode.ORDER_NOT_FOUND, null, null, null, null,
                    null, null, dispatchId, null, OffsetDateTime.now(BUSINESS_ZONE));
        }

        MaintainRecord order = maintainRecordMapper.selectById(assignment.getOrderId());
        if (!ReceiptStatus.ACCEPTED.name().equals(assignment.getReceiptStatus())) {
            ReasonCode storedReason = assignment.getReasonCode() == null
                    ? ReasonCode.INTERNAL_ERROR : ReasonCode.valueOf(assignment.getReasonCode());
            OutcomeStatus storedOutcome = switch (storedReason) {
                case VERSION_CONFLICT, ORDER_ALREADY_ASSIGNED, IDEMPOTENCY_KEY_CONFLICT -> OutcomeStatus.CONFLICT;
                default -> OutcomeStatus.FAILED;
            };
            return outcome(assignment, order, storedOutcome, storedReason);
        }
        if (order == null) {
            return outcome(assignment, null, OutcomeStatus.FAILED, ReasonCode.ORDER_NOT_FOUND);
        }
        OrderStatus status = toOrderStatus(order.getStatus());
        boolean assignedAsRequested = (status == OrderStatus.ASSIGNED || status == OrderStatus.COMPLETED)
                && assignment.getWorkerId().equals(order.getMiantainId())
                && assignment.getResultVersion() != null
                && order.getVersion() >= assignment.getResultVersion();
        if (assignedAsRequested) {
            return outcome(assignment, order, OutcomeStatus.ASSIGNED, null);
        }
        if (order.getMiantainId() != null && !assignment.getWorkerId().equals(order.getMiantainId())) {
            return outcome(assignment, order, OutcomeStatus.CONFLICT, ReasonCode.ORDER_ALREADY_ASSIGNED);
        }
        return outcome(assignment, order, OutcomeStatus.PENDING, null);
    }

    MaintainRecord requireOrder(Integer orderId) {
        MaintainRecord order = maintainRecordMapper.selectById(orderId);
        if (order == null) {
            throw new DispatchBusinessException(HttpStatus.NOT_FOUND,
                    ReasonCode.ORDER_NOT_FOUND, "工单不存在");
        }
        return order;
    }

    private WorkerSnapshotV1 toWorkerSnapshot(RepairmanDispatchProfile profile, List<String> skills,
                                               int currentLoad, OffsetDateTime snapshotAt) {
        return new WorkerSnapshotV1(CONTRACT_VERSION, profile.getWorkerId().toString(),
                profile.getTenantId(), List.copyOf(skills), profile.getRegionCode(),
                profile.getShiftStatus(), profile.getAvailable(), currentLoad,
                profile.getCapacity(), snapshotAt);
    }

    private AssignmentOutcomeV1 outcome(DispatchAssignment assignment, MaintainRecord order,
                                         OutcomeStatus outcomeStatus, ReasonCode reasonCode) {
        return new AssignmentOutcomeV1(CONTRACT_VERSION, outcomeStatus, reasonCode,
                assignment.getOrderId().toString(),
                order == null || order.getMiantainId() == null ? null : order.getMiantainId().toString(),
                order == null ? null : toOrderStatus(order.getStatus()),
                order == null ? null : order.getVersion(), assignment.getTraceId(), assignment.getEventId(),
                assignment.getDispatchId(), assignment.getIdempotencyKey(), OffsetDateTime.now(BUSINESS_ZONE));
    }

    static String tenant(MaintainRecord order) {
        return order.getTenantId() == null || order.getTenantId().isBlank()
                ? DEFAULT_TENANT : order.getTenantId();
    }
}
