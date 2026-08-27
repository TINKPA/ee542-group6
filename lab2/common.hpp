// EE542 Lab2 - shared definitions (framing + packet headers).
#pragma once
#include <arpa/inet.h>
#include <cstdint>
#include <cstring>
#include <unistd.h>
#include <vector>
static constexpr uint8_t MAGIC = 0x5A;
enum PktType : uint8_t { PT_DATA=1, PT_END_ROUND=2, PT_NAK=3, PT_DONE=4 };
enum TcpType : uint8_t { TT_HELLO=1, TT_HELLO_ACK=2, TT_DONE=3 };
struct PktHdr { uint32_t seq; uint16_t round; uint8_t type; uint8_t magic; };
static_assert(sizeof(PktHdr) == 8, "PktHdr must be 8 bytes");
