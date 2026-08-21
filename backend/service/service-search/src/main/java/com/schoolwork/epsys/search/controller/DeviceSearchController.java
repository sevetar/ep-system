package com.schoolwork.epsys.search.controller; // 定义该类所在的包

import com.schoolwork.epsys.common.Result;
import com.schoolwork.epsys.device.client.DeviceFeignClient;
import com.schoolwork.epsys.model.device.Deviceinstance;
import com.schoolwork.epsys.model.device.MaintainRecord;
import com.schoolwork.epsys.model.search.DeviceInstanceDoc; // 导入设备实例文档类

import com.schoolwork.epsys.search.service.DeviceSearchService; // 导入设备搜索服务接口
import com.schoolwork.epsys.utils.WebUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*; // 导入Spring Web相关注解

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List; // 导入List集合类
import java.util.Map;

import static com.schoolwork.epsys.common.ResultCodeEnum.LAZY_ERROR;

/**
 * 设备搜索接口，负责 Elasticsearch 设备文档的检索、写入、删除和详情查询。
 */
@RestController // 标注为Spring的REST控制器组件
@RequestMapping("/search") // 定义该控制器的基础请求路径
public class DeviceSearchController {


    @Autowired // 自动注入设备搜索服务
    private DeviceFeignClient deviceFeignClient;

    private final DeviceSearchService deviceSearchService;
    // 定义设备搜索服务的依赖

    public DeviceSearchController(DeviceSearchService deviceSearchService) {
        this.deviceSearchService = deviceSearchService;
        // 构造方法注入设备搜索服务
    }

    /**
     * 按关键词检索设备文档，并通过设备服务补充对应的设备实例信息。
     */
    @RequestMapping // 处理GET请求，执行搜索操作
    public void search(HttpServletRequest req,HttpServletResponse resp, @RequestParam("keyword") String keyword) {
        List<DeviceInstanceDoc> deviceInstanceDocs = deviceSearchService.search(keyword);
        List<Integer> deviceInstanceIds =new ArrayList<>();
        for (DeviceInstanceDoc deviceInstanceDoc : deviceInstanceDocs) {
            Integer deviceInstanceId = deviceInstanceDoc.getId();
            if (deviceInstanceId != null) {
                deviceInstanceIds.add(deviceInstanceId);
            }
        }
        if (deviceInstanceIds == null) {
            Result result= Result.error("没有维护记录");
            WebUtil.writeJson(resp, result);
            return;
        }
        List<Deviceinstance> Deviceinstances = deviceFeignClient.getDeviceInstanceListById(deviceInstanceIds);
        Map map=new HashMap();
        map.put("deviceInstanceDocs", deviceInstanceDocs);
        map.put("Deviceinstances", Deviceinstances);


        System.out.println("ES 搜索关键词：" + keyword);
        System.out.println("ES 返回数量：" + deviceInstanceDocs.size());


        Result result = Result.ok(map);
        WebUtil.writeJson(resp, result);
    }

    /**
     * 将设备实例文档写入 Elasticsearch 索引。
     */
    @PostMapping // 处理POST请求，执行保存操作
    public void save(@RequestBody DeviceInstanceDoc doc) {
        deviceSearchService.save(doc);
        // 调用服务的save方法保存设备实例文档
    }

    /**
     * 根据文档 ID 删除 Elasticsearch 中的设备实例文档。
     */
    @DeleteMapping("/{id}") // 处理DELETE请求，执行删除操作
    public void delete(@PathVariable Integer id) {
        System.out.println("删除设备实例文档：" + id);
        deviceSearchService.deleteById(id);
        // 调用服务的deleteById方法删除设备实例文档
    }

    /**
     * 根据文档 ID 查询单个设备实例文档。
     */
    @GetMapping("/{id}") // 处理GET请求，执行获取操作
    public DeviceInstanceDoc get(@PathVariable Integer id) {
        return deviceSearchService.getById(id);

        // 调用服务的getById方法获取设备实例文档
    }
}
