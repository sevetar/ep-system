package com.schoolwork.epsys.device.saga;

import com.schoolwork.epsys.device.mapper.DeviceBindingResultOutboxMapper;
import com.schoolwork.epsys.model.device.DeviceBindingResultOutbox;
import com.schoolwork.epsys.mq.outbox.OutboxStore;
import org.springframework.stereotype.Component;

import java.util.Date;
import java.util.List;

@Component
public class DeviceBindingResultOutboxStore implements OutboxStore<DeviceBindingResultOutbox> {

    private final DeviceBindingResultOutboxMapper mapper;

    public DeviceBindingResultOutboxStore(DeviceBindingResultOutboxMapper mapper) {
        this.mapper = mapper;
    }

    @Override
    public List<DeviceBindingResultOutbox> findPublishable(Date now, Date staleBefore, int limit) {
        return mapper.findPublishable(now, staleBefore, limit);
    }

    @Override
    public boolean claim(DeviceBindingResultOutbox event, Date now, Date staleBefore) {
        return mapper.claimForPublishing(event.getId(), now, staleBefore) == 1;
    }

    @Override
    public int retryCount(DeviceBindingResultOutbox event) {
        return event.getRetryCount();
    }

    @Override
    public void markPublished(DeviceBindingResultOutbox event) {
        mapper.markPublished(event.getId());
    }

    @Override
    public void markFailed(DeviceBindingResultOutbox event, Date nextRetryAt, String error) {
        mapper.markFailed(event.getId(), nextRetryAt, error);
    }
}
