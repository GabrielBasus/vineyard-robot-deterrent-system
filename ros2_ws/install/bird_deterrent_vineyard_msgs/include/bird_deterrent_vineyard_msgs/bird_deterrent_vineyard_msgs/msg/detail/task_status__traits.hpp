// generated from rosidl_generator_cpp/resource/idl__traits.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/TaskStatus.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__TRAITS_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__TRAITS_HPP_

#include <stdint.h>

#include <sstream>
#include <string>
#include <type_traits>

#include "bird_deterrent_vineyard_msgs/msg/detail/task_status__struct.hpp"
#include "rosidl_runtime_cpp/traits.hpp"

namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

inline void to_flow_style_yaml(
  const TaskStatus & msg,
  std::ostream & out)
{
  out << "{";
  // member: t
  {
    out << "t: ";
    rosidl_generator_traits::value_to_yaml(msg.t, out);
    out << ", ";
  }

  // member: event
  {
    out << "event: ";
    rosidl_generator_traits::value_to_yaml(msg.event, out);
    out << ", ";
  }

  // member: robot_id
  {
    out << "robot_id: ";
    rosidl_generator_traits::value_to_yaml(msg.robot_id, out);
    out << ", ";
  }

  // member: task_id
  {
    out << "task_id: ";
    rosidl_generator_traits::value_to_yaml(msg.task_id, out);
    out << ", ";
  }

  // member: type
  {
    out << "type: ";
    rosidl_generator_traits::value_to_yaml(msg.type, out);
    out << ", ";
  }

  // member: x
  {
    out << "x: ";
    rosidl_generator_traits::value_to_yaml(msg.x, out);
    out << ", ";
  }

  // member: y
  {
    out << "y: ";
    rosidl_generator_traits::value_to_yaml(msg.y, out);
    out << ", ";
  }

  // member: role
  {
    out << "role: ";
    rosidl_generator_traits::value_to_yaml(msg.role, out);
    out << ", ";
  }

  // member: extra
  {
    out << "extra: ";
    rosidl_generator_traits::value_to_yaml(msg.extra, out);
  }
  out << "}";
}  // NOLINT(readability/fn_size)

inline void to_block_style_yaml(
  const TaskStatus & msg,
  std::ostream & out, size_t indentation = 0)
{
  // member: t
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "t: ";
    rosidl_generator_traits::value_to_yaml(msg.t, out);
    out << "\n";
  }

  // member: event
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "event: ";
    rosidl_generator_traits::value_to_yaml(msg.event, out);
    out << "\n";
  }

  // member: robot_id
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "robot_id: ";
    rosidl_generator_traits::value_to_yaml(msg.robot_id, out);
    out << "\n";
  }

  // member: task_id
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "task_id: ";
    rosidl_generator_traits::value_to_yaml(msg.task_id, out);
    out << "\n";
  }

  // member: type
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "type: ";
    rosidl_generator_traits::value_to_yaml(msg.type, out);
    out << "\n";
  }

  // member: x
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "x: ";
    rosidl_generator_traits::value_to_yaml(msg.x, out);
    out << "\n";
  }

  // member: y
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "y: ";
    rosidl_generator_traits::value_to_yaml(msg.y, out);
    out << "\n";
  }

  // member: role
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "role: ";
    rosidl_generator_traits::value_to_yaml(msg.role, out);
    out << "\n";
  }

  // member: extra
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "extra: ";
    rosidl_generator_traits::value_to_yaml(msg.extra, out);
    out << "\n";
  }
}  // NOLINT(readability/fn_size)

inline std::string to_yaml(const TaskStatus & msg, bool use_flow_style = false)
{
  std::ostringstream out;
  if (use_flow_style) {
    to_flow_style_yaml(msg, out);
  } else {
    to_block_style_yaml(msg, out);
  }
  return out.str();
}

}  // namespace msg

}  // namespace bird_deterrent_vineyard_msgs

namespace rosidl_generator_traits
{

[[deprecated("use bird_deterrent_vineyard_msgs::msg::to_block_style_yaml() instead")]]
inline void to_yaml(
  const bird_deterrent_vineyard_msgs::msg::TaskStatus & msg,
  std::ostream & out, size_t indentation = 0)
{
  bird_deterrent_vineyard_msgs::msg::to_block_style_yaml(msg, out, indentation);
}

[[deprecated("use bird_deterrent_vineyard_msgs::msg::to_yaml() instead")]]
inline std::string to_yaml(const bird_deterrent_vineyard_msgs::msg::TaskStatus & msg)
{
  return bird_deterrent_vineyard_msgs::msg::to_yaml(msg);
}

template<>
inline const char * data_type<bird_deterrent_vineyard_msgs::msg::TaskStatus>()
{
  return "bird_deterrent_vineyard_msgs::msg::TaskStatus";
}

template<>
inline const char * name<bird_deterrent_vineyard_msgs::msg::TaskStatus>()
{
  return "bird_deterrent_vineyard_msgs/msg/TaskStatus";
}

template<>
struct has_fixed_size<bird_deterrent_vineyard_msgs::msg::TaskStatus>
  : std::integral_constant<bool, false> {};

template<>
struct has_bounded_size<bird_deterrent_vineyard_msgs::msg::TaskStatus>
  : std::integral_constant<bool, false> {};

template<>
struct is_message<bird_deterrent_vineyard_msgs::msg::TaskStatus>
  : std::true_type {};

}  // namespace rosidl_generator_traits

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__TRAITS_HPP_
