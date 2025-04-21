# class Estimator(object):
#     def report_states(self, stats: dict):
#         '''
#         stats is a dict with the following items
#         {
#             "send_time_ms": uint,
#             "arrival_time_ms": uint,
#             "payload_type": int,
#             "sequence_number": uint,
#             "ssrc": int,
#             "padding_length": uint,
#             "header_length": uint,
#             "payload_size": uint
#         }
#         '''
#         pass

#     def get_estimated_bandwidth(self)->int:

#         return int(1e6) # 1Mbps



class Estimator(object):
    def __init__(self):
        self.packets = {}  # 存储所有收到的数据包信息
        self.last_sequence_seen = None  # 上一个收到的序列号
        self.missing_packets = 0  # 丢失的数据包数量
        self.total_packets = 0  # 接收到的总数据包数量
        self.total_bytes = 0  # 收到的总字节数
        self.start_time_ms = None  # 第一个包到达的时间
        self.last_time_ms = None  # 最近一个包到达的时间
        self.last_valid_throughput = 300000 # bps, 一个默认的启动值
        import os
        # 使用环境变量获取路径，如果不存在，默认写入当前目录(容器内的/app)
        # 注意：OUTPUT_DIR 需要在 docker run 命令中通过 -e 传递进来
        output_dir = os.getenv("OUTPUT_DIR", ".") # 使用 "." 作为备用，表示当前目录
        log_file_path = os.path.join(output_dir, "estimator_output.log")

        try:
            # 确保目录存在 (在容器内可能需要创建)
            os.makedirs(output_dir, exist_ok=True)
            print(f"Attempting to open log file at: {log_file_path}")
            # 使用 UTF-8 编码以支持非ASCII字符（虽然当前日志是英文）
            self.log_file = open(log_file_path, "w", encoding="utf-8")
            print(f"Successfully opened log file: {log_file_path}")
        except Exception as e:
            print(f"Failed to open log file at {log_file_path}: {e}")
            self.log_file = None

    def report_states(self, stats: dict):
        '''
        stats是包含以下项目的字典
        {
            "send_time_ms": uint,
            "arrival_time_ms": uint,
            "payload_type": int,
            "sequence_number": uint,
            "ssrc": int,
            "padding_length": uint,
            "header_length": uint,
            "payload_size": uint
        }
        '''
        sequence_number = stats["sequence_number"]
        arrival_time_ms = stats["arrival_time_ms"]
        payload_size = stats["payload_size"]
        
        # 记录第一个包的到达时间
        if self.start_time_ms is None:
            self.start_time_ms = arrival_time_ms
        
        self.last_time_ms = arrival_time_ms
        
        # 更新总字节数
        self.total_bytes += payload_size
        
        # 检测丢包
        if self.last_sequence_seen is not None:
            expected_sequence = (self.last_sequence_seen + 1) % 65536  # 假设序列号是16位的
            if sequence_number != expected_sequence:
                # 如果序列号不连续，可能发生了丢包
                if sequence_number > expected_sequence:
                    self.missing_packets += (sequence_number - expected_sequence)
                else:  # 处理序列号循环的情况
                    self.missing_packets += (65536 - expected_sequence + sequence_number)
        
        self.last_sequence_seen = sequence_number
        self.total_packets += 1
        self.packets[sequence_number] = stats
        
        # 记录关键信息到日志
        if self.total_packets % 100 == 0:  # 每100个包记录一次
            packet_loss = self.get_packet_loss_rate()
            throughput = self.get_throughput()
            # NOTE Don't use the chinese!!!
            self.log_file.write(f"Time: {arrival_time_ms}ms, Packet loss rate: {packet_loss:.4f}, Throughput: {throughput} bps\n")
            self.log_file.flush()  # 确保数据写入文件

    def get_packet_loss_rate(self) -> float:
        """计算丢包率"""
        if self.total_packets + self.missing_packets == 0:
            return 0.0
        return self.missing_packets / (self.total_packets + self.missing_packets)
    
    def get_throughput(self) -> int:
        """计算吞吐量 (bps)"""
        if self.last_time_ms is None or self.start_time_ms is None or self.last_time_ms <= self.start_time_ms:
            # 时间不足或无效，返回上一次计算的有效吞吐量或默认值
            if self.log_file: self.log_file.write(f"Throughput calculation skipped: insufficient time data. Returning last valid: {self.last_valid_throughput} bps\n")
            return self.last_valid_throughput

        duration_ms = self.last_time_ms - self.start_time_ms
        if duration_ms <= 0:
             # 避免除以零或负数
             if self.log_file: self.log_file.write(f"Throughput calculation skipped: non-positive duration {duration_ms}ms. Returning last valid: {self.last_valid_throughput} bps\n")
             return self.last_valid_throughput

        throughput_bps = (self.total_bytes * 8 * 1000) / duration_ms
        calculated_throughput = int(throughput_bps)

        # 如果计算结果有效（大于0），则更新最后有效吞吐量
        if calculated_throughput > 0:
            self.last_valid_throughput = calculated_throughput
            if self.log_file: self.log_file.write(f"Throughput calculated: {calculated_throughput} bps (bytes={self.total_bytes}, duration={duration_ms}ms)\n")
            return calculated_throughput
        else:
            # 如果计算结果为0或负数，仍然返回上一次有效值
            if self.log_file: self.log_file.write(f"Throughput calculated as zero or negative. Returning last valid: {self.last_valid_throughput} bps\n")
            return self.last_valid_throughput

    def get_estimated_bandwidth(self) -> int:
        bandwidth = self.get_throughput() # get_throughput 现在会返回一个有效值
        # 如果计算出的带宽仍然非常低（例如低于某个阈值），可以考虑强制返回一个最低值
        min_bandwidth_bps = 100000 # 100 kbps
        if bandwidth < min_bandwidth_bps:
             if self.log_file: self.log_file.write(f"Calculated bandwidth {bandwidth} bps is below minimum threshold. Returning minimum: {min_bandwidth_bps} bps\n")
             bandwidth = min_bandwidth_bps

        # 记录带宽估计到日志
        if self.log_file:
            try:
                self.log_file.write(f"Estimated bandwidth reported: {bandwidth} bps\n")
                self.log_file.flush()
            except Exception as e:
                 print(f"Failed to write estimated bandwidth to log: {e}")
        else:
             print(f"Log file not available. Estimated bandwidth: {bandwidth} bps")
        return bandwidth

    def __del__(self):
        # 关闭日志文件
        if hasattr(self, 'log_file'):
            self.log_file.close()