package com.schoolwork.epsys.device.dispatch.trigger;

import com.schoolwork.epsys.device.mapper.DispatchEventOutboxMapper;
import com.schoolwork.epsys.model.device.DispatchEventOutbox;
import com.schoolwork.epsys.mq.outbox.OutboxStore;
import org.springframework.stereotype.Component;

import java.util.Date;
import java.util.List;

@Component
public class DispatchOutboxStore implements OutboxStore<DispatchEventOutbox> {

    private final DispatchEventOutboxMapper mapper;

    public DispatchOutboxStore(DispatchEventOutboxMapper mapper) {
        this.mapper = mapper;
    }

    @Override
    public List<DispatchEventOutbox> findPublishable(Date now, Date staleBefore, int limit) {
        return mapper.findPublishable(now, staleBefore, limit);
    }

    @Override
    public boolean claim(DispatchEventOutbox event, Date now, Date staleBefore) {
        return mapper.claimForPublishing(event.getId(), now, staleBefore) == 1;
    }

    @Override
    public int retryCount(DispatchEventOutbox event) {
        return event.getRetryCount();
    }

    @Override
    public void markPublished(DispatchEventOutbox event) {
        mapper.markPublished(event.getId());
    }

    @Override
    public void markFailed(DispatchEventOutbox event, Date nextRetryAt, String error) {
        mapper.markFailed(event.getId(), nextRetryAt, error);
    }
}
