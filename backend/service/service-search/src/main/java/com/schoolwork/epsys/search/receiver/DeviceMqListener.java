package com.schoolwork.epsys.search.receiver;

import com.schoolwork.epsys.model.search.DeviceInstanceDoc;
import com.schoolwork.epsys.search.repository.DeviceInstanceRepository;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.elasticsearch.core.ElasticsearchOperations;
import org.springframework.stereotype.Component;

import static com.schoolwork.epsys.mq.constant.MqConst.*;


@Component
public class DeviceMqListener  {

    @Autowired
    private ElasticsearchOperations elasticsearchOperations;

    @Autowired
    private DeviceInstanceRepository repository;

    @RabbitListener(queues = INCREASE_DEVICE_INSTANCE_QUEUE)
    public void addOrUpdate(DeviceInstanceDoc deviceInstanceDoc) {
        System.out.println("Received message: " + deviceInstanceDoc.toString());
        elasticsearchOperations.save(deviceInstanceDoc);

    }

    @RabbitListener(queues = DECREASE_DEVICE_INSTANCE_QUEUE)
    public void delete(Integer maintainRecordId) {
        System.out.println("Received message: " + maintainRecordId.toString());
        elasticsearchOperations.delete(maintainRecordId.toString(), DeviceInstanceDoc.class);
    }
}
