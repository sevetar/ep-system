package com.schoolwork.epsys.device.knowledge;

import com.schoolwork.epsys.device.mapper.WorkOrderKnowledgeOutboxMapper;
import com.schoolwork.epsys.model.device.WorkOrderKnowledgeOutbox;
import com.schoolwork.epsys.mq.outbox.OutboxStore;
import org.springframework.stereotype.Component;

import java.util.Date;
import java.util.List;

@Component
public class WorkOrderKnowledgeOutboxStore implements OutboxStore<WorkOrderKnowledgeOutbox> {

    private final WorkOrderKnowledgeOutboxMapper mapper;

    public WorkOrderKnowledgeOutboxStore(WorkOrderKnowledgeOutboxMapper mapper) {
        this.mapper = mapper;
    }

    @Override
    public List<WorkOrderKnowledgeOutbox> findPublishable(Date now, Date staleBefore, int limit) {
        return mapper.findPublishable(now, staleBefore, limit);
    }

    @Override
    public boolean claim(WorkOrderKnowledgeOutbox event, Date now, Date staleBefore) {
        return mapper.claimForPublishing(event.getId(), now, staleBefore) == 1;
    }

    @Override
    public int retryCount(WorkOrderKnowledgeOutbox event) {
        return event.getRetryCount();
    }

    @Override
    public void markPublished(WorkOrderKnowledgeOutbox event) {
        mapper.markPublished(event.getId());
    }

    @Override
    public void markFailed(WorkOrderKnowledgeOutbox event, Date nextRetryAt, String error) {
        mapper.markFailed(event.getId(), nextRetryAt, error);
    }
}
