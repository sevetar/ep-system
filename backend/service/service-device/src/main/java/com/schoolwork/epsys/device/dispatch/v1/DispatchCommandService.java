package com.schoolwork.epsys.device.dispatch.v1;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.schoolwork.epsys.device.mapper.DispatchAssignmentMapper;
import com.schoolwork.epsys.model.device.DispatchAssignment;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import static com.schoolwork.epsys.device.dispatch.v1.DispatchContracts.*;

@Service
public class DispatchCommandService {

    private static final Logger log = LoggerFactory.getLogger(DispatchCommandService.class);

    private final RedissonClient redissonClient;
    private final DispatchTransactionService transactionService;
    private final DispatchAssignmentMapper assignmentMapper;

    public DispatchCommandService(RedissonClient redissonClient,
                                  DispatchTransactionService transactionService,
                                  DispatchAssignmentMapper assignmentMapper) {
        this.redissonClient = redissonClient;
        this.transactionService = transactionService;
        this.assignmentMapper = assignmentMapper;
    }

    public AssignmentReceiptV1 assign(AssignmentCommandV1 command) {
        validateContract(command);
        String commandHash = DispatchCommandHasher.hash(command);
        RLock lock = redissonClient.getLock("order:lock:" + command.orderId());
        boolean locked = false;
        try {
            locked = lock.tryLock();
            if (!locked) {
                return receipt(command, ReceiptStatus.REJECTED,
                        ReasonCode.ORDER_BUSY_RETRYABLE, null);
            }
            AssignmentReceiptV1 receipt = transactionService.assign(command, commandHash);
            log.info("dispatch receipt traceId={} eventId={} dispatchId={} idempotencyKey={} orderId={} "
                            + "workerId={} expectedVersion={} observedVersion={} status={} reasonCode={}",
                    command.traceId(), command.eventId(), command.dispatchId(), command.idempotencyKey(),
                    command.orderId(), command.workerId(), command.expectedVersion(), receipt.observedVersion(),
                    receipt.receiptStatus(), receipt.reasonCode());
            return receipt;
        } catch (DuplicateKeyException ex) {
            log.info("dispatch unique constraint conflict orderId={} dispatchId={}",
                    command.orderId(), command.dispatchId());
            DispatchAssignment existing = assignmentMapper.selectOne(
                    Wrappers.<DispatchAssignment>lambdaQuery()
                            .eq(DispatchAssignment::getIdempotencyKey, command.idempotencyKey()));
            if (existing != null && commandHash.equals(existing.getCommandHash())) {
                return receipt(command, ReceiptStatus.ALREADY_APPLIED, null, existing.getResultVersion());
            }
            return receipt(command, ReceiptStatus.REJECTED,
                    ReasonCode.ORDER_ALREADY_ASSIGNED, null);
        } catch (DispatchBusinessException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new DispatchBusinessException(HttpStatus.SERVICE_UNAVAILABLE,
                    ReasonCode.DEPENDENCY_UNAVAILABLE, "派单依赖暂时不可用");
        } finally {
            if (locked && lock.isHeldByCurrentThread()) {
                lock.unlock();
            }
        }
    }

    private void validateContract(AssignmentCommandV1 command) {
        if (!CONTRACT_VERSION.equals(command.contractVersion())) {
            throw new DispatchBusinessException(HttpStatus.BAD_REQUEST,
                    ReasonCode.UNSUPPORTED_CONTRACT_VERSION, "不支持的派单合同版本");
        }
        if (!DEFAULT_TENANT.equals(command.tenantId())) {
            throw new DispatchBusinessException(HttpStatus.FORBIDDEN,
                    ReasonCode.FORBIDDEN, "v1 仅允许 default 租户");
        }
        try {
            Integer.parseInt(command.orderId());
            Integer.parseInt(command.workerId());
        } catch (NumberFormatException ex) {
            throw new DispatchBusinessException(HttpStatus.BAD_REQUEST,
                    ReasonCode.INVALID_REQUEST, "orderId 或 workerId 超出 Java Integer 范围");
        }
    }

    private AssignmentReceiptV1 receipt(AssignmentCommandV1 command, ReceiptStatus status,
                                         ReasonCode reasonCode, Integer observedVersion) {
        return new AssignmentReceiptV1(CONTRACT_VERSION, status, reasonCode,
                command.orderId(), command.workerId(), command.expectedVersion(), observedVersion,
                command.traceId(), command.eventId(), command.dispatchId(), command.idempotencyKey());
    }
}
