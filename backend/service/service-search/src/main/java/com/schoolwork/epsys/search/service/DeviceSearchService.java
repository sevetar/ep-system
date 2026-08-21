package com.schoolwork.epsys.search.service; // 定义该接口所在的包

import com.schoolwork.epsys.model.search.DeviceInstanceDoc; // 导入设备实例文档类

import java.util.List; // 导入List集合类

public interface DeviceSearchService { // 定义设备搜索服务接口
    void save(DeviceInstanceDoc doc); // 添加或更新设备实例文档
    void deleteById(Integer id);      // 根据ID删除设备实例文档
    DeviceInstanceDoc getById(Integer id); // 根据ID获取设备实例文档
    List<DeviceInstanceDoc> search(String keyword); // 根据关键字搜索设备实例文档

}
