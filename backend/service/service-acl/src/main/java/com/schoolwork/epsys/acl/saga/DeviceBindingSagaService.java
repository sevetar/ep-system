package com.schoolwork.epsys.acl.saga;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schoolwork.epsys.acl.mapper.DeviceBindingOutboxMapper;
import com.schoolwork.epsys.acl.mapper.DevicetousersMapper;
import com.schoolwork.epsys.model.acl.DeviceBindingOutbox;
import com.schoolwork.epsys.model.acl.Devicetousers;
import com.schoolwork.epsys.model.shared.DeviceBindingRequestedEventV1;
import com.schoolwork.epsys.model.shared.DeviceBindingResultEventV1;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Date;
import java.util.Objects;

import static com.schoolwork.epsys.model.shared.DeviceBindingContracts.*;

@Service
public class DeviceBindingSagaService {

    private final DevicetousersMapper relationMapper;
    private final DeviceBindingOutboxMapper outboxMapper;
    private final ObjectMapper objectMapper;

    public DeviceBindingSagaService(DevicetousersMapper relationMapper,
                                    DeviceBindingOutboxMapper outboxMapper,
                                    ObjectMapper objectMapper) {
        this.relationMapper = relationMapper;
        this.outboxMapper = outboxMapper;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public SagaRequestResult requestBind(Integer userId, Integer deviceId, String requestId) {
        Devicetousers existing = relationMapper.findByDeviceId(deviceId);
        if (existing != null) {
            if (!Objects.equals(existing.getUserId(), userId)) {
                return SagaRequestResult.conflict("该设备已被其他用户领用");
            }
            DeviceBindingStatus status = status(existing);
            if (status == DeviceBindingStatus.ACTIVE) {
                return SagaRequestResult.applied(existing.getRequestId(), "该设备已在我的设备中");
            }
            if (status == DeviceBindingStatus.PENDING_BIND) {
                return SagaRequestResult.pending(existing.getRequestId(), "设备领用请求处理中");
            }
            if (status == DeviceBindingStatus.PENDING_UNBIND) {
                return SagaRequestResult.conflict("设备解绑请求处理中，暂不能重新领用");
            }
            if (relationMapper.transition(existing.getId(), DeviceBindingStatus.FAILED.name(),
                    DeviceBindingStatus.PENDING_BIND.name(), requestId) != 1) {
                return SagaRequestResult.conflict("设备领用状态已变化，请重试");
            }
        } else {
            Devicetousers relation = new Devicetousers();
            relation.setUserId(userId);
            relation.setDeviceId(deviceId);
            relation.setBindingStatus(DeviceBindingStatus.PENDING_BIND.name());
            relation.setRequestId(requestId);
            relation.setUpdatedAt(new Date());
            try {
                relationMapper.insert(relation);
            } catch (DuplicateKeyException exception) {
                return SagaRequestResult.conflict("设备领用请求发生并发冲突，请刷新后重试");
            }
        }
        createOutbox(requestId, BIND_REQUESTED, userId, deviceId);
        return SagaRequestResult.pending(requestId, "设备领用请求已受理");
    }

    @Transactional
    public SagaRequestResult requestUnbind(Integer userId, Integer deviceId, String requestId) {
        Devicetousers existing = relationMapper.findByDeviceId(deviceId);
        if (existing == null) {
            return SagaRequestResult.applied(requestId, "设备已处于未领用状态");
        }
        if (!Objects.equals(existing.getUserId(), userId)) {
            return SagaRequestResult.conflict("该设备不属于当前用户");
        }
        DeviceBindingStatus status = status(existing);
        if (status == DeviceBindingStatus.PENDING_UNBIND) {
            return SagaRequestResult.pending(existing.getRequestId(), "设备解绑请求处理中");
        }
        if (status != DeviceBindingStatus.ACTIVE) {
            return SagaRequestResult.conflict("当前领用关系状态不可解绑: " + status);
        }
        if (relationMapper.transition(existing.getId(), DeviceBindingStatus.ACTIVE.name(),
                DeviceBindingStatus.PENDING_UNBIND.name(), requestId) != 1) {
            return SagaRequestResult.conflict("设备领用状态已变化，请重试");
        }
        createOutbox(requestId, UNBIND_REQUESTED, userId, deviceId);
        return SagaRequestResult.pending(requestId, "设备解绑请求已受理");
    }

    @Transactional
    public void applyResult(DeviceBindingResultEventV1 event) {
        if (!SCHEMA_VERSION.equals(event.schemaVersion())) {
            throw new IllegalArgumentException("不支持的设备领用结果合同: " + event.schemaVersion());
        }
        Devicetousers relation = relationMapper.findByDeviceId(event.deviceId());
        if (relation == null || !Objects.equals(relation.getRequestId(), event.requestId())) {
            return;
        }
        boolean succeeded = "SUCCEEDED".equals(event.status());
        if (BIND_REQUESTED.equals(event.eventType())) {
            if (status(relation) != DeviceBindingStatus.PENDING_BIND) {
                return;
            }
            relationMapper.applyResult(relation.getId(), event.requestId(),
                    DeviceBindingStatus.PENDING_BIND.name(),
                    succeeded ? DeviceBindingStatus.ACTIVE.name() : DeviceBindingStatus.FAILED.name(),
                    succeeded ? null : event.reasonCode());
            return;
        }
        if (UNBIND_REQUESTED.equals(event.eventType())) {
            if (status(relation) != DeviceBindingStatus.PENDING_UNBIND) {
                return;
            }
            if (succeeded) {
                relationMapper.completeUnbind(relation.getId(), event.requestId());
            } else {
                relationMapper.applyResult(relation.getId(), event.requestId(),
                        DeviceBindingStatus.PENDING_UNBIND.name(), DeviceBindingStatus.ACTIVE.name(),
                        event.reasonCode());
            }
            return;
        }
        throw new IllegalArgumentException("未知设备领用事件类型: " + event.eventType());
    }

    public boolean isActiveOwner(Integer userId, Integer deviceId) {
        Devicetousers relation = relationMapper.findByDeviceId(deviceId);
        return relation != null && Objects.equals(relation.getUserId(), userId)
                && status(relation) == DeviceBindingStatus.ACTIVE;
    }

    private void createOutbox(String requestId, String eventType, Integer userId, Integer deviceId) {
        String eventId = "device-binding-request:" + requestId;
        DeviceBindingRequestedEventV1 event = new DeviceBindingRequestedEventV1(
                SCHEMA_VERSION, eventId, requestId, eventType, userId, deviceId, Instant.now());
        DeviceBindingOutbox outbox = new DeviceBindingOutbox();
        outbox.setEventId(eventId);
        outbox.setRequestId(requestId);
        outbox.setEventType(eventType);
        outbox.setUserId(userId);
        outbox.setDeviceId(deviceId);
        outbox.setPayload(toJson(event));
        outbox.setPublishStatus("PENDING");
        outbox.setRetryCount(0);
        outbox.setNextRetryAt(new Date());
        outbox.setCreatedAt(new Date());
        outbox.setUpdatedAt(new Date());
        outboxMapper.insert(outbox);
    }

    private DeviceBindingStatus status(Devicetousers relation) {
        String value = relation.getBindingStatus();
        return value == null ? DeviceBindingStatus.ACTIVE : DeviceBindingStatus.valueOf(value);
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("无法序列化设备领用Saga事件", exception);
        }
    }

    public record SagaRequestResult(boolean accepted, boolean alreadyApplied, String status,
                                    String requestId, String message) {
        static SagaRequestResult pending(String requestId, String message) {
            return new SagaRequestResult(true, false, "PENDING", requestId, message);
        }

        static SagaRequestResult applied(String requestId, String message) {
            return new SagaRequestResult(true, true, "ACTIVE", requestId, message);
        }

        static SagaRequestResult conflict(String message) {
            return new SagaRequestResult(false, false, "CONFLICT", null, message);
        }
    }
}
