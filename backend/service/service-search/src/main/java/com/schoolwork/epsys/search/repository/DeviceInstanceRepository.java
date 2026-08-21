package com.schoolwork.epsys.search.repository; // 定义该类所在的包

import com.schoolwork.epsys.model.search.DeviceInstanceDoc; // 导入设备实例文档类
import org.springframework.data.elasticsearch.repository.ElasticsearchRepository; // 导入ElasticsearchRepository接口
import org.springframework.stereotype.Repository; // 导入Repository注解

import java.util.List; // 导入List集合类

@Repository // 标注为Spring的Repository组件
public interface DeviceInstanceRepository extends ElasticsearchRepository<DeviceInstanceDoc, Integer> {
    // 继承ElasticsearchRepository，泛型为设备实例文档类和主键类型

    // 按设备序列号模糊搜索
    List<DeviceInstanceDoc> findBySerialNumberContaining(String keyword); 
    // 定义方法，根据设备序列号包含指定关键字进行模糊查询

    // 按位置模糊搜索
    List<DeviceInstanceDoc> findByLocationContaining(String keyword); 
    // 定义方法，根据位置包含指定关键字进行模糊查询

    // 组合搜索：按位置或设备序列号模糊搜索
    List<DeviceInstanceDoc> findByLocationContainingOrSerialNumberContaining(String location, String serialNumber); 
    // 定义方法，

    List<DeviceInstanceDoc> findByLocationContainingOrSerialNumberContainingOrStatus(String location, String serialNumber, String status);
}
