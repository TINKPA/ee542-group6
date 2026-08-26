/* EE 542 Lab 2 - wire format contract (WIP).
 * Design: blast + NACK rounds. The sender paces DATA at a target rate and
 * never waits for an ACK; the receiver reports what is still missing.
 */
#ifndef EE542_PROTOCOL_H
#define EE542_PROTOCOL_H
#include <stdint.h>
#define FT_MAGIC   0x45453542u   /* "EE5B" */
#define FT_VERSION 1
enum ft_type { FT_HELLO=1, FT_HELLO_ACK=2, FT_DATA=3, FT_NACK=4, FT_DONE=5, FT_FIN=6 };
#endif
