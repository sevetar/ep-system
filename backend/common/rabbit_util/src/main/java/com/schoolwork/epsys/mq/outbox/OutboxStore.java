package com.schoolwork.epsys.mq.outbox;

import java.util.Date;
import java.util.List;

/** 持久化 Outbox 的最小存储策略，可靠状态始终保存在数据库中。 */
public interface OutboxStore<T> {

    List<T> findPublishable(Date now, Date staleBefore, int limit);

    boolean claim(T event, Date now, Date staleBefore);

    int retryCount(T event);

    void markPublished(T event);

    void markFailed(T event, Date nextRetryAt, String error);
}
