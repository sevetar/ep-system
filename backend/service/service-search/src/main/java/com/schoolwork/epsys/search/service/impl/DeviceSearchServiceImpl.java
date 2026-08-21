package com.schoolwork.epsys.search.service.impl; // 定义该类所在的包


import com.schoolwork.epsys.model.search.DeviceInstanceDoc;
import com.schoolwork.epsys.search.repository.DeviceInstanceRepository;
import com.schoolwork.epsys.search.service.DeviceSearchService;
import org.springframework.data.elasticsearch.core.ElasticsearchOperations;
import org.springframework.data.elasticsearch.core.SearchHits;
import org.springframework.data.elasticsearch.core.query.Criteria;
import org.springframework.data.elasticsearch.core.query.CriteriaQuery;
import org.springframework.data.elasticsearch.core.query.Query;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.stream.Collectors;


@Service
public class DeviceSearchServiceImpl implements DeviceSearchService {

    private final DeviceInstanceRepository deviceInstanceRepository;
    private final ElasticsearchOperations elasticsearchOperations;

    public DeviceSearchServiceImpl(DeviceInstanceRepository deviceInstanceRepository,
                                   ElasticsearchOperations elasticsearchOperations) {
        this.deviceInstanceRepository = deviceInstanceRepository;
        this.elasticsearchOperations = elasticsearchOperations;
    }

    @Override
    public void save(DeviceInstanceDoc doc) {
        deviceInstanceRepository.save(doc);
    }

    @Override
    public void deleteById(Integer id) {
        deviceInstanceRepository.deleteById(id);
    }

    @Override
    public DeviceInstanceDoc getById(Integer id) {
        return deviceInstanceRepository.findById(id).orElse(null);
    }


    @Override
    public List<DeviceInstanceDoc> search(String keyword) {
        return deviceInstanceRepository.findByLocationContainingOrSerialNumberContainingOrStatus(
                keyword, keyword, keyword);
    }



}

