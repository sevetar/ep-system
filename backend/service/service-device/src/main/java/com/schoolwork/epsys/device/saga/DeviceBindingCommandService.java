package com.schoolwork.epsys.device.saga;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schoolwork.epsys.device.mapper.DeviceBindingCommandMapper;
import com.schoolwork.epsys.device.mapper.DeviceBindingResultOutboxMapper;
import com.schoolwork.epsys.device.mapper.DeviceinstanceMapper;
import com.schoolwork.epsys.model.device.DeviceBindingCommand;
import com.schoolwork.epsys.model.device.DeviceBindingResultOutbox;
import com.schoolwork.epsys.model.device.Deviceinstance;
import com.schoolwork.epsys.model.shared.DeviceBindingRequestedEventV1;
import com.schoolwork.epsys.model.shared.DeviceBindingResultEventV1;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Date;

import static com.schoolwork.epsys.model.shared.DeviceBindingContracts.*;

@Service
public class DeviceBindingCommandService {

    private static final String SUCCEEDED = "SUCCEEDED";
    private static final String FAILED = "FAILED";

    private final DeviceinstanceMapper deviceMapper;
    private final DeviceBindingCommandMapper commandMapper;
    private final DeviceBindingResultOutboxMapper resultOutboxMapper;
    private final ObjectMapper objectMapper;

    public DeviceBindingCommandService(DeviceinstanceMapper deviceMapper,
                                       DeviceBindingCommandMapper commandMapper,
                                       DeviceBindingResultOutboxMapper resultOutboxMapper,
                                       ObjectMapper objectMapper) {
        this.deviceMapper = deviceMapper;
        this.commandMapper = commandMapper;
        this.resultOutboxMapper = resultOutboxMapper;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public void handle(DeviceBindingRequestedEventV1 event) {
        validate(event);
        if (commandMapper.findByRequestId(event.requestId()) != null) {
            return;
        }

        String expectedStatus;
        String targetStatus;
        if (BIND_REQUESTED.equals(event.eventType())) {
            expectedStatus = "闲置";
            targetStatus = "使用";
        } else {
            expectedStatus = "使用";
            targetStatus = "闲置";
        }

        int updated = deviceMapper.transitionStatus(event.deviceId(), expectedStatus, targetStatus);
        String resultStatus = updated == 1 ? SUCCEEDED : FAILED;
        String reasonCode = updated == 1 ? null : failureReason(event.deviceId());

        DeviceBindingCommand command = new DeviceBindingCommand();
        command.setRequestId(event.requestId());
        command.setEventId(event.eventId());
        command.setEventType(event.eventType());
        command.setUserId(event.userId());
        command.setDeviceId(event.deviceId());
        command.setResultStatus(resultStatus);
        command.setReasonCode(reasonCode);
        command.setCreatedAt(new Date());
        command.setUpdatedAt(new Date());
        commandMapper.insert(command);

        createResultOutbox(event, resultStatus, reasonCode);
    }

    private void validate(DeviceBindingRequestedEventV1 event) {
        if (!SCHEMA_VERSION.equals(event.schemaVersion())) {
            throw new IllegalArgumentException("不支持的设备领用请求合同: " + event.schemaVersion());
        }
        if (!BIND_REQUESTED.equals(event.eventType()) && !UNBIND_REQUESTED.equals(event.eventType())) {
            throw new IllegalArgumentException("未知设备领用事件类型: " + event.eventType());
        }
        if (event.requestId() == null || event.requestId().isBlank()
                || event.eventId() == null || event.eventId().isBlank()
                || event.userId() == null || event.deviceId() == null) {
            throw new IllegalArgumentException("设备领用请求缺少必填字段");
        }
    }

    private String failureReason(Integer deviceId) {
        Deviceinstance device = deviceMapper.selectById(deviceId);
        return device == null ? "DEVICE_NOT_FOUND" : "DEVICE_STATUS_CONFLICT";
    }

    private void createResultOutbox(DeviceBindingRequestedEventV1 request,
                                    String status, String reasonCode) {
        String eventId = "device-binding-result:" + request.requestId();
        DeviceBindingResultEventV1 result = new DeviceBindingResultEventV1(
                SCHEMA_VERSION, eventId, request.requestId(), request.eventType(),
                request.userId(), request.deviceId(), status, reasonCode, Instant.now());
        DeviceBindingResultOutbox outbox = new DeviceBindingResultOutbox();
        outbox.setEventId(eventId);
        outbox.setRequestId(request.requestId());
        outbox.setEventType(request.eventType());
        outbox.setUserId(request.userId());
        outbox.setDeviceId(request.deviceId());
        outbox.setPayload(toJson(result));
        outbox.setPublishStatus("PENDING");
        outbox.setRetryCount(0);
        outbox.setNextRetryAt(new Date());
        outbox.setCreatedAt(new Date());
        outbox.setUpdatedAt(new Date());
        resultOutboxMapper.insert(outbox);
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("无法序列化设备领用结果事件", exception);
        }
    }
}
