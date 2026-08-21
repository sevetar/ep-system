package com.schoolwork.epsys.acl.saga;

import com.schoolwork.epsys.acl.mapper.DeviceBindingOutboxMapper;
import com.schoolwork.epsys.model.acl.DeviceBindingOutbox;
import com.schoolwork.epsys.mq.outbox.OutboxStore;
import org.springframework.stereotype.Component;

import java.util.Date;
import java.util.List;

@Component
public class DeviceBindingOutboxStore implements OutboxStore<DeviceBindingOutbox> {

    private final DeviceBindingOutboxMapper mapper;

    public DeviceBindingOutboxStore(DeviceBindingOutboxMapper mapper) {
        this.mapper = mapper;
    }

    @Override
    public List<DeviceBindingOutbox> findPublishable(Date now, Date staleBefore, int limit) {
        return mapper.findPublishable(now, staleBefore, limit);
    }

    @Override
    public boolean claim(DeviceBindingOutbox event, Date now, Date staleBefore) {
        return mapper.claimForPublishing(event.getId(), now, staleBefore) == 1;
    }

    @Override
    public int retryCount(DeviceBindingOutbox event) {
        return event.getRetryCount();
    }

    @Override
    public void markPublished(DeviceBindingOutbox event) {
        mapper.markPublished(event.getId());
    }

    @Override
    public void markFailed(DeviceBindingOutbox event, Date nextRetryAt, String error) {
        mapper.markFailed(event.getId(), nextRetryAt, error);
    }
}
