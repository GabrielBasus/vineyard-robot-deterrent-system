// generated from rosidl_generator_cpp/resource/idl__struct.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Zone.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__STRUCT_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__STRUCT_HPP_

#include <algorithm>
#include <array>
#include <memory>
#include <string>
#include <vector>

#include "rosidl_runtime_cpp/bounded_vector.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


// Include directives for member types
// Member 'polygon'
#include "bird_deterrent_vineyard_msgs/msg/detail/polygon2_d__struct.hpp"

#ifndef _WIN32
# define DEPRECATED__bird_deterrent_vineyard_msgs__msg__Zone __attribute__((deprecated))
#else
# define DEPRECATED__bird_deterrent_vineyard_msgs__msg__Zone __declspec(deprecated)
#endif

namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

// message struct
template<class ContainerAllocator>
struct Zone_
{
  using Type = Zone_<ContainerAllocator>;

  explicit Zone_(rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  : polygon(_init)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->robot_id = "";
    }
  }

  explicit Zone_(const ContainerAllocator & _alloc, rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  : robot_id(_alloc),
    polygon(_alloc, _init)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->robot_id = "";
    }
  }

  // field types and members
  using _robot_id_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _robot_id_type robot_id;
  using _polygon_type =
    bird_deterrent_vineyard_msgs::msg::Polygon2D_<ContainerAllocator>;
  _polygon_type polygon;
  using _neighbors_type =
    std::vector<std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>>>;
  _neighbors_type neighbors;

  // setters for named parameter idiom
  Type & set__robot_id(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->robot_id = _arg;
    return *this;
  }
  Type & set__polygon(
    const bird_deterrent_vineyard_msgs::msg::Polygon2D_<ContainerAllocator> & _arg)
  {
    this->polygon = _arg;
    return *this;
  }
  Type & set__neighbors(
    const std::vector<std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>>> & _arg)
  {
    this->neighbors = _arg;
    return *this;
  }

  // constant declarations

  // pointer types
  using RawPtr =
    bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator> *;
  using ConstRawPtr =
    const bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator> *;
  using SharedPtr =
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator>>;
  using ConstSharedPtr =
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator> const>;

  template<typename Deleter = std::default_delete<
      bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator>>>
  using UniquePtrWithDeleter =
    std::unique_ptr<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator>, Deleter>;

  using UniquePtr = UniquePtrWithDeleter<>;

  template<typename Deleter = std::default_delete<
      bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator>>>
  using ConstUniquePtrWithDeleter =
    std::unique_ptr<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator> const, Deleter>;
  using ConstUniquePtr = ConstUniquePtrWithDeleter<>;

  using WeakPtr =
    std::weak_ptr<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator>>;
  using ConstWeakPtr =
    std::weak_ptr<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator> const>;

  // pointer types similar to ROS 1, use SharedPtr / ConstSharedPtr instead
  // NOTE: Can't use 'using' here because GNU C++ can't parse attributes properly
  typedef DEPRECATED__bird_deterrent_vineyard_msgs__msg__Zone
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator>>
    Ptr;
  typedef DEPRECATED__bird_deterrent_vineyard_msgs__msg__Zone
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator> const>
    ConstPtr;

  // comparison operators
  bool operator==(const Zone_ & other) const
  {
    if (this->robot_id != other.robot_id) {
      return false;
    }
    if (this->polygon != other.polygon) {
      return false;
    }
    if (this->neighbors != other.neighbors) {
      return false;
    }
    return true;
  }
  bool operator!=(const Zone_ & other) const
  {
    return !this->operator==(other);
  }
};  // struct Zone_

// alias to use template instance with default allocator
using Zone =
  bird_deterrent_vineyard_msgs::msg::Zone_<std::allocator<void>>;

// constant definitions

}  // namespace msg

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__STRUCT_HPP_
