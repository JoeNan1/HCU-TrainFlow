// Bounded workflow smoke: deliberately simple FP32 implementations, not a tuning result.
#include <hip/hip_runtime.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <vector>

#define HIP_OK(call) do { auto e = (call); if (e != hipSuccess) { \
  std::cerr << #call << ": " << hipGetErrorString(e) << "\n"; return 2; } } while (0)

__global__ void baseline(const float* x, const float* y, float* z, int n) {
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i < n) z[i] = 0.5f * x[i] + y[i];
  return;
}
__global__ void candidate(const float* x, const float* y, float* z, int n) {
  for (int i = blockIdx.x * blockDim.x + threadIdx.x; i < n;
       i += blockDim.x * gridDim.x) z[i] = 0.5f * x[i] + y[i];
  return;
}

int main() {
  const auto start = std::chrono::steady_clock::now();
  const int cap = (1 << 20) + 16; // Three arrays: ~12 MiB, below 512 MiB budget.
  HIP_OK(hipSetDevice(0));
  hipDeviceProp_t prop{};
  HIP_OK(hipGetDeviceProperties(&prop, 0));
  float *x = nullptr, *y = nullptr, *z = nullptr;
  HIP_OK(hipMalloc(&x, cap * sizeof(float)));
  HIP_OK(hipMalloc(&y, cap * sizeof(float)));
  HIP_OK(hipMalloc(&z, cap * sizeof(float)));
  std::vector<float> hx(cap), hy(cap), hz(cap), back(cap);
  int executed = 0, failures = 0;
  for (int seed : {0, 1, 7}) for (int n : {1, 257, 4099, 1 << 20}) {
    for (int i = 0; i < cap; ++i) {
      hx[i] = float((i * 17 + seed * 13) % 257 - 128) / 64.0f;
      hy[i] = float((i * 11 + seed * 7) % 251 - 125) / 64.0f;
    }
    HIP_OK(hipMemcpy(x, hx.data(), cap * sizeof(float), hipMemcpyHostToDevice));
    HIP_OK(hipMemcpy(y, hy.data(), cap * sizeof(float), hipMemcpyHostToDevice));
    for (int variant = 0; variant < 2; ++variant) {
      std::fill(hz.begin(), hz.end(), -12345.0f);
      HIP_OK(hipMemcpy(z, hz.data(), cap * sizeof(float), hipMemcpyHostToDevice));
      if (variant == 0) hipLaunchKernelGGL(baseline, dim3((n + 255) / 256), dim3(256), 0, 0, x, y, z, n);
      else hipLaunchKernelGGL(candidate, dim3(std::min(128, (n + 127) / 128)), dim3(128), 0, 0, x, y, z, n);
      HIP_OK(hipGetLastError());
      HIP_OK(hipDeviceSynchronize());
      HIP_OK(hipMemcpy(hz.data(), z, cap * sizeof(float), hipMemcpyDeviceToHost));
      ++executed;
      for (int i = 0; i < cap; ++i) {
        // Independent host oracle in double; bounded dyadic inputs are exactly representable.
        const float expected = i < n ? float(0.5 * double(hx[i]) + double(hy[i])) : -12345.0f;
        if (!std::isfinite(hz[i]) || hz[i] != expected) { ++failures; break; }
      }
      HIP_OK(hipMemcpy(back.data(), x, cap * sizeof(float), hipMemcpyDeviceToHost));
      if (back != hx) ++failures;
      HIP_OK(hipMemcpy(back.data(), y, cap * sizeof(float), hipMemcpyDeviceToHost));
      if (back != hy) ++failures;
    }
  }
  hipEvent_t begin, end;
  HIP_OK(hipEventCreate(&begin)); HIP_OK(hipEventCreate(&end));
  std::vector<float> bt, ct;
  const int n = 1 << 20, launches = 100;
  for (int pair = 0; pair < 3; ++pair) for (int slot = 0; slot < 2; ++slot) {
    const bool cand = (slot + pair) % 2;
    for (int warmup = 0; warmup < 5; ++warmup) {
      if (cand) hipLaunchKernelGGL(candidate, dim3(128), dim3(128), 0, 0, x, y, z, n);
      else hipLaunchKernelGGL(baseline, dim3((n + 255) / 256), dim3(256), 0, 0, x, y, z, n);
    }
    HIP_OK(hipGetLastError()); HIP_OK(hipDeviceSynchronize());
    HIP_OK(hipEventRecord(begin));
    for (int repeat = 0; repeat < launches; ++repeat) {
      if (cand) hipLaunchKernelGGL(candidate, dim3(128), dim3(128), 0, 0, x, y, z, n);
      else hipLaunchKernelGGL(baseline, dim3((n + 255) / 256), dim3(256), 0, 0, x, y, z, n);
    }
    HIP_OK(hipGetLastError()); HIP_OK(hipEventRecord(end)); HIP_OK(hipEventSynchronize(end));
    float ms = 0; HIP_OK(hipEventElapsedTime(&ms, begin, end));
    (cand ? ct : bt).push_back(ms / launches);
    if (std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() > 55) {
      std::cerr << "Internal device-run budget exhausted\n"; return 3;
    }
  }
  HIP_OK(hipEventDestroy(begin)); HIP_OK(hipEventDestroy(end));
  HIP_OK(hipFree(x)); HIP_OK(hipFree(y)); HIP_OK(hipFree(z));
  std::cout << std::setprecision(9) << "{\"executed\":" << executed << ",\"failures\":" << failures
    << ",\"device_name\":\"" << prop.name << "\",\"architecture\":\"" << prop.gcnArchName
    << "\",\"baseline_times\":[";
  for (size_t i = 0; i < bt.size(); ++i) std::cout << (i ? "," : "") << bt[i];
  std::cout << "],\"candidate_times\":[";
  for (size_t i = 0; i < ct.size(); ++i) std::cout << (i ? "," : "") << ct[i];
  std::cout << "]}\n";
  return failures ? 1 : 0;
}
