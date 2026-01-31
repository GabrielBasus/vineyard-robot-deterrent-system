// generated from rosidl_generator_cpp/resource/idl__traits.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Task.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__TRAITS_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__TRAITS_HPP_

#include <stdint.h>

#include <sstream>
#include <string>
#include <type_traits>

#include "bird_deterrent_vineyard_msgs/msg/detail/task__struct.hpp"
#include "rosidl_runtime_cpp/traits.hpp"

namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

inline void to_flow_style_yaml(
  const Task & msg,
  std::ostream & out)
{
  out << "{";
  // member: id
  {
    out << "id: ";
    rosidl_generator_traits::value_to_yaml(msg.id, out);
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

  // member: time
  {
    out << "time: ";
    rosidl_generator_traits::value_to_yaml(msg.time, out);
    out << ", ";
  }

  // member: assigned_primary
  {
    out << "assigned_primary: ";
    rosidl_generator_traits::value_to_yaml(msg.assigned_primary, out);
    out << ", ";
  }

  // member: assigned_secondary
  {
    out << "assigned_secondary: ";
    rosidl_generator_traits::value_to_yaml(msg.assigned_secondary, out);
    out << ", ";
  }

  // member: score
  {
    out << "score: ";
    rosidl_generator_traits::value_to_yaml(msg.score, out);
  }
  out << "}";
}  // NOLINT(readability/fn_size)

inline void to_block_style_yaml(
  const Task & msg,
  std::ostream & out, size_t indentation = 0)
{
  // member: id
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "id: ";
    rosidl_generator_traits::value_to_yaml(msg.id, out);
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

  // member: time
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "time: ";
    rosidl_generator_traits::value_to_yaml(msg.time, out);
    out << "\n";
  }

  // member: assigned_primary
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "assigned_primary: ";
    rosidl_generator_traits::value_to_yaml(msg.assigned_primary, out);
    out << "\n";
  }

  // member: assigned_secondary
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "assigned_secondary: ";
    rosidl_generator_traits::value_to_yaml(msg.assigned_secondary, out);
    out << "\n";
  }

  // member: score
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "score: ";
    rosidl_generator_traits::value_to_yaml(msg.score, out);
    out << "\n";
  }
}  // NOLINT(readability/fn_size)

inline std::string to_yaml(const Task & msg, bool use_flow_style = false)
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
  const bird_deterrent_vineyard_msgs::msg::Task & msg,
  std::ostream & out, size_t indentation = 0)
{
  bird_deterrent_vineyard_msgs::msg::to_block_style_yaml(msg, out, indentation);
}

[[deprecated("use bird_deterrent_vineyard_msgs::msg::to_yaml() instead")]]
inline std::string to_yaml(const bird_deterrent_vineyard_msgs::msg::Task & msg)
{
  return bird_deterrent_vineyard_msgs::msg::to_yaml(msg);
}

template<>
inline const char * data_type<bird_deterrent_vineyard_msgs::msg::Task>()
{
  return "bird_deterrent_vineyard_msgs::msg::Task";
}

template<>
inline const char * name<bird_deterrent_vineyard_msgs::msg::Task>()
{
  return "bird_deterrent_vineyard_msgs/msg/Task";
}

template<>
struct has_fixed_size<bird_deterrent_vineyard_msgs::msg::Task>
  : std::integral_constant<bool, false> {};

template<>
struct has_bounded_size<bird_deterrent_vineyard_msgs::msg::Task>
  : std::integral_constant<bool, false> {};

template<>
struct is_message<bird_deterrent_vineyard_msgs::msg::Task>
  : std::true_type {};

}  // namespace rosidl_generator_traits

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__TRAITS_HPP_
