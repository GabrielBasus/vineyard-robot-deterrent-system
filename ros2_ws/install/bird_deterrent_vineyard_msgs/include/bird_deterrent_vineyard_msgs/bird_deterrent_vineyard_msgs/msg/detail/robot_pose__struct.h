// generated from rosidl_generator_c/resource/idl__struct.h.em
// with input from bird_deterrent_vineyard_msgs:msg/RobotPose.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ROBOT_POSE__STRUCT_H_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ROBOT_POSE__STRUCT_H_

#ifdef __cplusplus
extern "C"
{
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


// Constants defined in the message

// Include directives for member types
// Member 'robot_id'
#include "rosidl_runtime_c/string.h"

/// Struct defined in msg/RobotPose in the package bird_deterrent_vineyard_msgs.
typedef struct bird_deterrent_vineyard_msgs__msg__RobotPose
{
  double t;
  rosidl_runtime_c__String robot_id;
  double x;
  double y;
} bird_deterrent_vineyard_msgs__msg__RobotPose;

// Struct for a sequence of bird_deterrent_vineyard_msgs__msg__RobotPose.
typedef struct bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence
{
  bird_deterrent_vineyard_msgs__msg__RobotPose * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence;

#ifdef __cplusplus
}
#endif

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ROBOT_POSE__STRUCT_H_
